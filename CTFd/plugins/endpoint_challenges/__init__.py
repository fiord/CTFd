import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from CTFd.models import Challenges, db
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils.plugins import register_script
from CTFd.plugins.migrations import upgrade
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.exceptions.challenges import ChallengeCreateException, ChallengeUpdateException
from CTFd.utils.user import get_current_user

import google.auth
from google.cloud import compute_v1
import uuid

class EndpointChallenge(Challenges):
    __tablename__ = "endpoint_challenge"
    __mapper_args__ = {"polymorphic_identity": "endpoint"}
    id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True)
    # Docker image for the challenge container
    docker_image = db.Column(db.String(255), nullable=False)

    def __init__(self, *args, **kwargs):
        super(EndpointChallenge, self).__init__(**kwargs)
        # Set the type for polymorphic inheritance
        self.type = "endpoint"
        # Set docker_image if provided, otherwise set a default
        self.docker_image = kwargs.get("docker_image", "")

class EndpointValueChallenge(BaseChallenge):
    id = "endpoint"
    name = "endpoint"
    templates = {
        "create": "/plugins/endpoint_challenges/templates/create.html",
        "update": "/plugins/endpoint_challenges/templates/update.html",
        "view": "/plugins/challenges/assets/view.html",
    }
    scripts = {
        "create": "/plugins/endpoint_challenges/assets/create.js",
        "update": "/plugins/endpoint_challenges/assets/update.js",
        # Use the standard challenge view script to satisfy CTFd's expected interface
        "view": "/plugins/challenges/assets/view.js",
    }
    route = "/plugins/endpoint_challenges/assets/"
    blueprint = Blueprint(
        "endpoint_challenges",
        __name__,
        template_folder="templates",
        static_folder="assets",
    )
    challenge_model = EndpointChallenge

    @classmethod
    def read(cls, challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.
        """
        data = super().read(challenge)

        # Try to get the endpoint-specific data
        endpoint_data = EndpointChallenge.query.filter_by(id=challenge.id).first()
        if endpoint_data:
            data.update({
                "docker_image": endpoint_data.docker_image,
            })
        else:
            # If endpoint data doesn't exist yet, provide a default
            data.update({
                "docker_image": "",
            })

        return data

    @classmethod
    def update(cls, challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.
        """
        data = request.form or request.get_json()

        # Update the base challenge data
        for attr, value in data.items():
            if attr in ["name", "description", "category", "value", "state", "max_attempts"]:
                setattr(challenge, attr, value)

        # Handle endpoint-specific data
        if "docker_image" in data:
            # Ensure the endpoint-specific data exists
            endpoint_data = EndpointChallenge.query.filter_by(id=challenge.id).first()
            if not endpoint_data:
                # Create the endpoint-specific data if it doesn't exist
                endpoint_data = EndpointChallenge(id=challenge.id, docker_image=data["docker_image"])
                db.session.add(endpoint_data)
            else:
                endpoint_data.docker_image = data["docker_image"]

        db.session.commit()
        return challenge

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)

    @classmethod
    def create_gce_instance(cls, challenge_id, user_id):
        """
        Create a GCE instance with Docker container using GCP API
        """
        challenge = EndpointChallenge.query.filter_by(id=challenge_id).first()
        if not challenge:
            return {"success": False, "error": "Challenge not found"}

        # Get GCP configuration from environment variables
        gcp_project = os.getenv('GCP_PROJECT')
        gcp_zone = os.getenv('GCP_ZONE')

        if not gcp_project or not gcp_zone:
            return {"success": False, "error": "GCP_PROJECT and GCP_ZONE environment variables must be set"}

        # Optional: allow overriding machine type via env (default: e2-micro for single-user workloads)
        gcp_machine_type = os.getenv('GCP_MACHINE_TYPE', 'e2-micro')

        try:
            # Authenticate with GCP
            credentials, project = google.auth.default()
            compute_client = compute_v1.InstancesClient(credentials=credentials)

            # TTL cleanup: delete instances older than 3 hours (default)
            try:
                ttl_hours = int(os.getenv('GCE_TTL_HOURS', '3'))
            except Exception:
                ttl_hours = 3
            try:
                now = datetime.now(timezone.utc)
                # filter only our app instances
                ttl_filter = "labels.app = ctfd-endpoint"
                for inst in compute_client.list(project=gcp_project, zone=gcp_zone, filter=ttl_filter):
                    # creation_timestamp is RFC3339 string
                    try:
                        created = datetime.strptime(inst.creation_timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
                    except Exception:
                        try:
                            created = datetime.strptime(inst.creation_timestamp, "%Y-%m-%dT%H:%M:%S%z")
                        except Exception:
                            created = None
                    if created and (now - created) > timedelta(hours=ttl_hours):
                        try:
                            op = compute_client.delete(project=gcp_project, zone=gcp_zone, instance=inst.name)
                            op.result()
                        except Exception:
                            pass
            except Exception:
                # TTL cleanup best-effort
                pass

            # Enforce 1 instance per user (list instances with our labels)
            try:
                filter_str = f"(labels.app = ctfd-endpoint) AND (labels.user_id = {user_id})"
                existing_instances = list(
                    compute_client.list(project=gcp_project, zone=gcp_zone, filter=filter_str)
                )
            except Exception:
                existing_instances = []

            # If same-challenge instance exists, return it
            for inst in existing_instances:
                labels = getattr(inst, 'labels', {}) or {}
                if str(labels.get('challenge_id')) == str(challenge_id):
                    ext_ip = None
                    for ni in inst.network_interfaces:
                        if ni.access_configs:
                            ext_ip = ni.access_configs[0].nat_i_p
                            break
                    return {
                        "success": True,
                        "instance_name": inst.name,
                        "external_ip": ext_ip,
                        "port": 80,
                        "status": inst.status,
                        "tags": list(inst.tags.items) if inst.tags and inst.tags.items else []
                    }

            # Otherwise delete any other existing instances for this user
            for inst in existing_instances:
                try:
                    del_op = compute_client.delete(project=gcp_project, zone=gcp_zone, instance=inst.name)
                    del_op.result()
                except Exception:
                    pass

            # Generate unique instance name
            instance_name = f"ctf-challenge-{challenge_id}-{user_id}-{uuid.uuid4().hex[:6]}"

            # Create the instance with Docker container
            instance = compute_v1.Instance()
            instance.name = instance_name
            instance.machine_type = f"zones/{gcp_zone}/machineTypes/{gcp_machine_type}"

            # Configure boot disk with Container-Optimized OS
            disk = compute_v1.AttachedDisk()
            disk.auto_delete = True
            disk.boot = True
            disk.initialize_params = compute_v1.AttachedDiskInitializeParams()
            disk.initialize_params.source_image = 'projects/cos-cloud/global/images/family/cos-stable'
            disk.initialize_params.disk_size_gb = 10
            instance.disks = [disk]

            # Configure network
            network_interface = compute_v1.NetworkInterface()
            network_interface.network = f"projects/{gcp_project}/global/networks/default"
            access_config = compute_v1.AccessConfig()
            access_config.name = 'External NAT'
            access_config.type_ = 'ONE_TO_ONE_NAT'
            network_interface.access_configs = [access_config]
            instance.network_interfaces = [network_interface]

            # Configure metadata for Docker container
            metadata = compute_v1.Metadata()
            metadata.items = [
                compute_v1.Items(key='gce-container-declaration', value=f'''spec:
  containers:
  - name: challenge-container
    image: {challenge.docker_image}
    ports:
    - containerPort: 80
    stdin: false
    tty: false
  restartPolicy: Always
'''),
                compute_v1.Items(key='google-logging-enabled', value='true')
            ]
            instance.metadata = metadata

            # Add network tags so that firewall rules can target this VM
            instance.tags = compute_v1.Tags(items=["ctfd-challenge"])  # open HTTP via FW rule

            # Attach labels to identify instance owner & challenge
            instance.labels = {
                "app": "ctfd-endpoint",
                "user_id": str(user_id),
                "challenge_id": str(challenge_id),
            }

            # Ensure firewall rule exists to allow HTTP (tcp:80) for instances with tag "ctfd-challenge"
            try:
                fw_client = compute_v1.FirewallsClient(credentials=credentials)
                fw_name = "ctfd-challenge-allow-http"
                # Check if firewall exists
                exists = False
                for fw in fw_client.list(project=gcp_project):
                    if fw.name == fw_name:
                        exists = True
                        break
                if not exists:
                    fw_rule = compute_v1.Firewall()
                    fw_rule.name = fw_name
                    fw_rule.direction = compute_v1.Firewall.Direction.INGRESS.name
                    fw_rule.network = f"projects/{gcp_project}/global/networks/default"
                    fw_rule.source_ranges = ["0.0.0.0/0"]
                    fw_rule.target_tags = ["ctfd-challenge"]
                    allowed = compute_v1.Allowed()
                    allowed.ip_protocol = "tcp"
                    allowed.ports = ["80"]
                    fw_rule.allowed = [allowed]
                    fw_insert = fw_client.insert(project=gcp_project, firewall_resource=fw_rule)
                    try:
                        fw_insert.result()
                    except Exception:
                        pass
            except Exception:
                # Don't fail instance creation if firewall ensure fails; surface network issues later
                pass

            # Create the instance
            operation = compute_client.insert(
                project=gcp_project,
                zone=gcp_zone,
                instance_resource=instance
            )

            # Wait for operation to complete
            operation.result()

            # Get the created instance to retrieve IP
            instance_info = compute_client.get(
                project=gcp_project,
                zone=gcp_zone,
                instance=instance_name
            )

            # Get external IP
            external_ip = None
            for interface in instance_info.network_interfaces:
                if interface.access_configs:
                    external_ip = interface.access_configs[0].nat_i_p
                    break

            if not external_ip:
                return {"success": False, "error": "Failed to get external IP"}

            return {
                "success": True,
                "instance_name": instance_name,
                "external_ip": external_ip,
                "port": 80,  # Container port
                "status": instance_info.status,
                "tags": list(instance_info.tags.items) if instance_info.tags and instance_info.tags.items else []
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


def load(app):
    app.logger.info("Loading Endpoint Challenges Plugin")
    upgrade(plugin_name="endpoint_challenges")
    CHALLENGE_CLASSES["endpoint"] = EndpointValueChallenge
    register_plugin_assets_directory(
        app, base_path="/plugins/endpoint_challenges/assets/"
    )
    # Also register our frontend enhancer so it's loaded on user-facing pages
    register_script("/plugins/endpoint_challenges/assets/view.js")

    @app.route("/api/v1/challenges/<int:challenge_id>/create_endpoint", methods=["POST"])
    def create_endpoint(challenge_id):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Authentication required"}), 403

        challenge = EndpointChallenge.query.filter_by(id=challenge_id).first()
        if not challenge:
            return jsonify({"success": False, "error": "Challenge not found"}), 404

        result = EndpointValueChallenge.create_gce_instance(challenge_id, user.id)
        return jsonify(result)

    return app
