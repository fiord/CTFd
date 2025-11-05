// Polyfill expected challenge interface if not already provided
if (!CTFd._internal) CTFd._internal = {};
if (!CTFd._internal.challenge) CTFd._internal.challenge = {};
if (typeof CTFd._internal.challenge.preRender !== 'function') {
    CTFd._internal.challenge.preRender = function () { };
}
if (typeof CTFd._internal.challenge.render === 'undefined') {
    CTFd._internal.challenge.render = null;
}
if (typeof CTFd._internal.challenge.postRender !== 'function') {
    CTFd._internal.challenge.postRender = function () { };
}
if (typeof CTFd._internal.challenge.submit !== 'function') {
    CTFd._internal.challenge.submit = function (preview) {
        var challenge_id = parseInt(CTFd.lib.$("#challenge-id").val());
        var submission = CTFd.lib.$("#challenge-input").val();

        var body = {
            challenge_id: challenge_id,
            submission: submission
        };
        var params = {};
        if (preview) {
            params["preview"] = true;
        }

        return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
            if (response.status === 429) {
                return response;
            }
            if (response.status === 403) {
                return response;
            }
            return response;
        });
    };
}

CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;

    // Check if this is the challenges page
    if (window.location.pathname.includes('/challenges')) {
        // Track currently-open challenge id
        let currentChallengeId = null;

        // Listen for the Bootstrap modal show event (safe even if Alpine isn't loaded yet)
        document.addEventListener('shown.bs.modal', function (event) {
            if (event.target && event.target.id === 'challenge-window') {
                // Immediately reset any residual UI state
                try {
                    const $loading = $('#endpoint-loading');
                    const $info = $('#endpoint-info');
                    const $btn = $('#create-endpoint-btn');
                    if ($loading.length) {
                        $loading.removeClass('d-inline-block');
                        $loading.hide();
                    }
                    if ($info.length) {
                        $info.hide();
                    }
                    if ($btn && $btn.length) {
                        $btn.show();
                    }
                } catch (e) { }
                // Force re-check on each open and inject UI immediately
                currentChallengeId = null;
                setTimeout(() => {
                    try { ensureEndpointUI(); } catch (e) { }
                    checkForEndpointChallenge();
                    // Fallback inline injection if still missing
                    try {
                        const $row = $('#challenge-window .submit-row');
                        if ($row.length && $('#create-endpoint-btn').length === 0) {
                            const endpointUI = `
                                <div class="col-12 mb-3">
                                    <div id="endpoint-info" class="alert alert-secondary" style="display: none;">
                                        <strong>Endpoint Created:</strong>
                                        <div id="endpoint-details"></div>
                                    </div>

                                    <button id="create-endpoint-btn" class="btn btn-primary me-2" onclick="createEndpoint()">
                                        Create Endpoint
                                    </button>

                                    <div id="endpoint-loading" style="display: none;">
                                        <div class="spinner-border spinner-border-sm" role="status">
                                            <span class="sr-only">Creating endpoint...</span>
                                        </div>
                                        <span class="ms-2">Creating endpoint...</span>
                                    </div>
                                </div>
                            `;
                            $row.prepend(endpointUI);
                        }
                    } catch (e) { }
                }, 100);
            }
        });

        function checkForEndpointChallenge() {
            // Get challenge ID from the modal
            const challengeId = $('#challenge-id').val();
            if (challengeId && challengeId !== currentChallengeId) {
                currentChallengeId = challengeId;
                // Check if this is an endpoint challenge by making an API call
                fetch(`/api/v1/challenges/${challengeId}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data && data.data && data.data.type === 'endpoint') {
                            injectEndpointUI();
                        }
                    })
                    .catch(err => console.log('Error checking challenge type:', err));
            }
        }

        function ensureEndpointUI(retries = 30) {
            const submitRow = $('.submit-row');
            if (submitRow.length > 0) {
                injectEndpointUI();
            } else if (retries > 0) {
                setTimeout(() => ensureEndpointUI(retries - 1), 100);
            }
        }

        function injectEndpointUI() {
            // Find the submit row in the challenge modal
            const submitRow = $('.submit-row');
            if (submitRow.length > 0) {
                // Always reset visibility to avoid stale state
                if ($('#endpoint-info').length) { $('#endpoint-info').hide(); }
                if ($('#endpoint-loading').length) { $('#endpoint-loading').hide(); }

                // Check if endpoint UI is already injected
                if ($('#create-endpoint-btn').length > 0) {
                    // Ensure button is visible when reopening modal
                    $('#create-endpoint-btn').show();
                    return; // Already injected (after reset)
                }

                // Add endpoint UI before the flag input
                const endpointUI = `
                    <div class="col-12 mb-3">
                        <div id="endpoint-info" class="alert alert-secondary" style="display: none;">
                            <strong>Endpoint Created:</strong>
                            <div id="endpoint-details"></div>
                        </div>

                        <button id="create-endpoint-btn" class="btn btn-primary me-2" onclick="createEndpoint()">
                            Create Endpoint
                        </button>

                        <div id="endpoint-loading" style="display: none;">
                            <div class="spinner-border spinner-border-sm" role="status">
                                <span class="sr-only">Creating endpoint...</span>
                            </div>
                            <span class="ms-2">Creating endpoint...</span>
                        </div>
                    </div>
                `;

                // Insert the endpoint UI at the beginning of the submit row
                submitRow.prepend(endpointUI);

                // Ensure elements are hidden on initial render
                $('#endpoint-info').hide();
                $('#endpoint-loading').removeClass('d-inline-block').hide();
            }
        }
    }

    // Make createEndpoint function available globally
    window.createEndpoint = function () {
        const challengeId = $("#challenge-id").val();

        // Show loading state
        $("#create-endpoint-btn").hide();
        $("#endpoint-loading").addClass('d-inline-block').show();

        // Make API call to create endpoint
        fetch(`/api/v1/challenges/${challengeId}/create_endpoint`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'CSRF-Token': (window.init && window.init.csrfNonce) ? window.init.csrfNonce : ''
            },
            credentials: 'same-origin',
        })
            .then(response => {
                if (!response.ok) {
                    return response.text().then(t => { throw new Error(`HTTP ${response.status}: ${t.substring(0, 200)}`); });
                }
                return response.json();
            })
            .then(data => {
                $("#endpoint-loading").hide();

                if (data.success) {
                    // Show endpoint information
                    $("#endpoint-details").html(`
                    <strong>IP Address:</strong> ${data.external_ip}<br>
                    <strong>Port:</strong> ${data.port}<br>
                    <strong>Instance:</strong> ${data.instance_name}<br>
                    <strong>URL:</strong> <a href="http://${data.external_ip}:${data.port}" target="_blank">http://${data.external_ip}:${data.port}</a>
                `);
                    $("#endpoint-info").show();
                } else {
                    // Show error
                    $("#endpoint-details").html(`<strong class="text-danger">Error:</strong> ${data.error}`);
                    $("#endpoint-info").show();
                    $("#create-endpoint-btn").show();
                }
            })
            .catch(error => {
                $("#endpoint-loading").hide();
                $("#endpoint-details").html(`<strong class="text-danger">Error:</strong> ${error.message}`);
                $("#endpoint-info").show();
                $("#create-endpoint-btn").show();
            });
    };
});
