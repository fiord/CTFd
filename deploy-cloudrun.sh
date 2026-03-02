#!/bin/bash
set -euo pipefail

# CTFd Cloud Run Deployment Script
# This script deploys CTFd to Google Cloud Run with Neon PostgreSQL and Upstash Redis

# ============================================
# Configuration
# ============================================
PROJECT_ID="${GCP_PROJECT_ID:-fiord-220408}"
REGION="${GCP_REGION:-us-west1}"
SERVICE_NAME="${SERVICE_NAME:-ctfd}"
SERVICE_ACCOUNT_NAME="${SERVICE_ACCOUNT_NAME:-ctfd-run-sa}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================
# Helper Functions
# ============================================
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================
# Check Prerequisites
# ============================================
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed. Please install it first."
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        log_error "docker is not installed. Please install it first."
        exit 1
    fi
    
    # Check if logged in to gcloud
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
        log_error "Not logged in to gcloud. Run: gcloud auth login"
        exit 1
    fi
    
    log_info "Prerequisites check passed."
}

# ============================================
# Set GCP Project
# ============================================
set_project() {
    log_info "Setting GCP project to: $PROJECT_ID"
    gcloud config set project "$PROJECT_ID"
}

# ============================================
# Enable Required APIs
# ============================================
enable_apis() {
    log_info "Enabling required GCP APIs..."
    gcloud services enable \
        cloudbuild.googleapis.com \
        run.googleapis.com \
        secretmanager.googleapis.com \
        artifactregistry.googleapis.com \
        containerregistry.googleapis.com
    log_info "APIs enabled successfully."
}

# ============================================
# Setup Secrets
# ============================================
setup_secrets() {
    log_info "Setting up secrets in Secret Manager..."
    
    # Check if secrets already exist
    SECRETS=("ctfd-database-url" "ctfd-redis-url" "ctfd-secret-key")
    
    for secret in "${SECRETS[@]}"; do
        if gcloud secrets describe "$secret" --project="$PROJECT_ID" &> /dev/null; then
            log_warn "Secret '$secret' already exists. Skipping creation."
        else
            log_info "Creating secret: $secret"
            echo -n "Please enter value for $secret: "
            read -s secret_value
            echo
            
            if [ -z "$secret_value" ]; then
                log_error "Secret value cannot be empty for $secret"
                exit 1
            fi
            
            echo -n "$secret_value" | gcloud secrets create "$secret" \
                --data-file=- \
                --replication-policy="automatic" \
                --project="$PROJECT_ID"
            
            log_info "Secret '$secret' created successfully."
        fi
    done
    
    # Create dedicated service account and grant Secret Manager access to it
    log_info "Creating dedicated service account and granting Secret Manager access..."
    SERVICE_ACCOUNT="$SERVICE_ACCOUNT_EMAIL"

    if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" --project="$PROJECT_ID" &> /dev/null; then
        gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
            --display-name="CTFd Cloud Run service account" \
            --project="$PROJECT_ID"
        log_info "Created service account: $SERVICE_ACCOUNT"
    else
        log_warn "Service account $SERVICE_ACCOUNT already exists. Skipping creation."
    fi

    for secret in "${SECRETS[@]}"; do
        gcloud secrets add-iam-policy-binding "$secret" \
            --member="serviceAccount:$SERVICE_ACCOUNT" \
            --role="roles/secretmanager.secretAccessor" \
            --project="$PROJECT_ID" &> /dev/null || true
    done

    log_info "Service account setup and secret bindings completed."
}

# ============================================
# Build and Deploy
# ============================================
build_and_deploy() {
    log_info "Building and deploying CTFd to Cloud Run..."
    
    # Use Cloud Build to build and deploy
    gcloud builds submit \
        --config=cloudbuild.yaml \
        --project="$PROJECT_ID" \
        --region="$REGION"
    
    log_info "Build and deployment completed."
}

# ============================================
# Get Service URL
# ============================================
get_service_url() {
    log_info "Getting service URL..."
    
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="value(status.url)")
    
    log_info "Service deployed successfully!"
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}CTFd URL: $SERVICE_URL${NC}"
    echo -e "${GREEN}============================================${NC}"
}

# ============================================
# Setup CloudFlare DNS (Manual Instructions)
# ============================================
cloudflare_instructions() {
    log_info "CloudFlare DNS Setup Instructions:"
    echo ""
    echo "1. Go to CloudFlare Dashboard: https://dash.cloudflare.com/"
    echo "2. Select your domain"
    echo "3. Go to DNS settings"
    echo "4. Add a CNAME record:"
    echo "   - Name: ctf (or your subdomain)"
    echo "   - Target: ghs.googlehosted.com"
    echo "   - Proxy status: Proxied (orange cloud)"
    echo ""
    echo "5. Then map your custom domain in Cloud Run:"
    echo "   gcloud run domain-mappings create --service=$SERVICE_NAME --domain=ctf.yourdomain.com --region=$REGION"
    echo ""
}

# ============================================
# Main Execution
# ============================================
main() {
    log_info "Starting CTFd Cloud Run deployment..."
    
    check_prerequisites
    set_project
    enable_apis
    
    # Ask if user wants to setup secrets
    echo -e "${YELLOW}Do you want to setup secrets now? (y/n)${NC}"
    read -r setup_secrets_choice
    if [[ "$setup_secrets_choice" =~ ^[Yy]$ ]]; then
        setup_secrets
    else
        log_warn "Skipping secrets setup. Make sure secrets are already configured."
    fi
    
    build_and_deploy
    # Configure Cloud Run service to run as the dedicated service account (if possible)
    log_info "Configuring Cloud Run service to use service account: $SERVICE_ACCOUNT_EMAIL"
    if ! gcloud run services update "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --service-account="$SERVICE_ACCOUNT_EMAIL" &> /dev/null; then
        log_warn "Could not update Cloud Run service to use $SERVICE_ACCOUNT_EMAIL. You may need iam.serviceAccounts.actAs permissions."
    else
        log_info "Cloud Run service configured to use $SERVICE_ACCOUNT_EMAIL"
    fi
    get_service_url
    cloudflare_instructions
    
    log_info "Deployment script completed!"
}

main "$@"
