// static/js/participants.js
document.addEventListener('DOMContentLoaded', function() {
    initializeTabs();
    initializeAuthMethodToggle();
    initializeUploadForm();
    initializeViewParticipants();
    initializeAPIConfig();
    initializeLogsTab();
    initializeModal();
    
    // Initialize API service
    window.apiService = new APIService();
});

function initializeTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function() {
            const subtabId = this.getAttribute('data-subtab');
            
            // Update active tab
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            
            // Show corresponding content
            document.querySelectorAll('.subtab-content').forEach(content => {
                content.classList.remove('active');
                if (content.id === subtabId) {
                    content.classList.add('active');
                    
                    // Refresh data when switching to specific tabs
                    if (subtabId === 'logs') {
                        loadAPILogs();
                    }
                }
            });
        });
    });
}

function initializeAuthMethodToggle() {
    const authMethodSelect = document.getElementById('auth-method');
    const tokenField = document.getElementById('token-field');
    
    if (authMethodSelect && tokenField) {
        authMethodSelect.addEventListener('change', function() {
            tokenField.style.display = this.value === 'none' ? 'none' : 'block';
        });
        
        // Trigger change event to set initial state
        authMethodSelect.dispatchEvent(new Event('change'));
    }
}

function initializeAPIConfig() {
    const apiConfigForm = document.getElementById('api-config-form');
    if (apiConfigForm) {
        apiConfigForm.addEventListener('submit', function(e) {
            e.preventDefault();
            saveAPIConfig();
        });
    }
    
    const startApiBtn = document.getElementById('start-api-btn');
    const stopApiBtn = document.getElementById('stop-api-btn');
    const testApiBtn = document.getElementById('test-api');
    const testConnectionBtn = document.getElementById('test-connection-btn');
    
    if (startApiBtn) {
        startApiBtn.addEventListener('click', function() {
            window.apiService.startService();
        });
    }
    
    if (stopApiBtn) {
        stopApiBtn.addEventListener('click', function() {
            window.apiService.stopService();
        });
    }
    
    if (testApiBtn) {
        testApiBtn.addEventListener('click', function() {
            window.apiService.testConnection();
        });
    }
    
    if (testConnectionBtn) {
        testConnectionBtn.addEventListener('click', function() {
            window.apiService.testConnection();
        });
    }
}

function saveAPIConfig() {
    const config = {
        endpoint_url: document.getElementById('api-endpoint').value,
        auth_method: document.getElementById('auth-method').value,
        api_key: document.getElementById('api-token').value,
        refresh_interval: parseInt(document.getElementById('refresh-interval').value),
        is_active: document.getElementById('api-active').checked,
        default_draw_id: document.getElementById('default-draw').value || null
    };
    
    // Validate required fields
    if (!config.endpoint_url) {
        showNotification('API Endpoint URL is required', 'error');
        return;
    }
    
    if (!config.default_draw_id) {
        showNotification('Default draw is required', 'error');
        return;
    }
    
    // Show loading state
    const submitBtn = document.querySelector('#api-config-form button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Saving...';
    submitBtn.disabled = true;
    
    fetch('/api/api-config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('API configuration saved successfully', 'success');
            // Update API service status
            window.apiService.updateStatus();
        } else {
            showNotification('Error saving API configuration: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error saving API configuration', 'error');
    })
    .finally(() => {
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    });
}

function initializeUploadForm() {
    const uploadForm = document.getElementById('upload-form');
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('participant-file');
            const drawSelect = document.getElementById('draw-select');
            
            if (!fileInput.files[0]) {
                showNotification('Please select a file to upload', 'error');
                return;
            }
            
            if (!drawSelect.value) {
                showNotification('Please select a draw', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('draw_id', drawSelect.value);
            
            // Show loading state
            const submitBtn = uploadForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Uploading...';
            submitBtn.disabled = true;
            
            fetch('/api/participants/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    let msg = data.message;
                    const problems = (data.summary && data.summary.problems) || [];
                    if (problems.length) {
                        msg += '. Rejected rows: ' + problems.slice(0, 5)
                            .map(p => `row ${p.line} (${p.reason})`).join('; ')
                            + (problems.length > 5 ? ` and ${problems.length - 5} more` : '');
                    }
                    showNotification(msg, problems.length ? 'warning' : 'success');
                    uploadForm.reset();
                    
                    // Refresh participants list if we're on the view tab
                    const viewDrawSelect = document.getElementById('view-draw-select');
                    if (viewDrawSelect && viewDrawSelect.value) {
                        loadParticipants(viewDrawSelect.value);
                    }
                } else {
                    showNotification(data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showNotification('Error uploading file', 'error');
            })
            .finally(() => {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            });
        });
    }
}

function initializeViewParticipants() {
    const viewDrawSelect = document.getElementById('view-draw-select');
    if (viewDrawSelect) {
        viewDrawSelect.addEventListener('change', function() {
            const drawId = this.value;
            loadParticipants(drawId);
        });
        
        // Load participants if a draw is already selected
        if (viewDrawSelect.value) {
            loadParticipants(viewDrawSelect.value);
        }
    }
}

function loadParticipants(drawId) {
    if (!drawId) {
        const table = document.getElementById('participants-table');
        table.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Select a draw to view participants</td></tr>';
        document.getElementById('participants-summary').style.display = 'none';
        return;
    }
    
    // Show loading state
    const table = document.getElementById('participants-table');
    table.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Loading participants...</td></tr>';
    
    fetch(`/api/participants/${drawId}`)
        .then(response => response.json())
        .then(participants => {
            if (participants.length === 0) {
                table.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No participants found for this draw</td></tr>';
                document.getElementById('participants-summary').style.display = 'none';
                return;
            }
            
            let verifiedCount = 0;
            let pendingCount = 0;
            
            table.innerHTML = participants.map(p => {
                const eligible = p.is_verified && !p.excluded_reason;
                if (eligible) verifiedCount++;
                else pendingCount++;
                const why = p.excluded_reason
                    ? (EXCLUSION_LABELS[p.excluded_reason] || p.excluded_reason)
                    : (p.is_verified ? 'Yes' : 'Not verified');

                return `
                <tr>
                    <td class="mono">${escapeHtml(p.phone_number)}</td>
                    <td>${escapeHtml(p.name || '')}</td>
                    <td>${escapeHtml(new Date(p.added_at).toLocaleString())}</td>
                    <td><span class="pill">${escapeHtml(p.source)}</span></td>
                    <td><span class="pill ${eligible ? 'pill-green' : 'pill-red'}">${escapeHtml(why)}</span></td>
                </tr>
                `;
            }).join('');
            
            // Update summary
            document.getElementById('total-participants').textContent = participants.length;
            document.getElementById('verified-count').textContent = verifiedCount;
            document.getElementById('pending-count').textContent = pendingCount;
            document.getElementById('participants-summary').style.display = 'block';
        })
        .catch(error => {
            console.error('Error:', error);
            table.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Error loading participants</td></tr>';
            document.getElementById('participants-summary').style.display = 'none';
        });
}

function initializeLogsTab() {
    const refreshLogsBtn = document.getElementById('refresh-logs');
    if (refreshLogsBtn) {
        refreshLogsBtn.addEventListener('click', function() {
            loadAPILogs();
        });
    }
    
    // Initialize response modal handlers
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('view-response-btn')) {
            const logId = e.target.getAttribute('data-log-id');
            viewResponseDetails(logId);
        }
    });
}

function initializeModal() {
    // Initialize Bootstrap modal properly
    const modalElement = document.getElementById('responseModal');
    if (modalElement && typeof bootstrap !== 'undefined') {
        window.responseModal = new bootstrap.Modal(modalElement);
        
        // Reset modal content when hidden
        modalElement.addEventListener('hidden.bs.modal', function () {
            resetModalContent();
        });
    }
}

function resetModalContent() {
    document.getElementById('detail-url').textContent = '-';
    document.getElementById('detail-timestamp').textContent = '-';
    document.getElementById('detail-status').textContent = '-';
    document.getElementById('detail-status').className = 'badge';
    document.getElementById('detail-added').textContent = '0';
    document.getElementById('response-details').textContent = 'Loading...';
}

function loadAPILogs() {
    const logsTable = document.getElementById('api-logs-table');
    const refreshBtn = document.getElementById('refresh-logs');
    
    if (!logsTable) return;
    
    // Show loading state
    const originalText = refreshBtn.textContent;
    refreshBtn.textContent = 'Loading...';
    refreshBtn.disabled = true;
    
    fetch('/api/response-logs')
        .then(response => response.json())
        .then(logs => {
            if (logs.length === 0) {
                logsTable.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No API response logs found</td></tr>';
                return;
            }
            
            logsTable.innerHTML = logs.map(log => `
                <tr class="${log.success ? 'table-success' : 'table-danger'}">
                    <td>${new Date(log.timestamp).toLocaleString()}</td>
                    <td>
                        <span class="badge ${log.response_status === 200 ? 'bg-success' : 'bg-danger'}">
                            ${log.response_status || 'N/A'}
                        </span>
                    </td>
                    <td>
                        <span class="badge bg-info">${log.participants_added}</span>
                    </td>
                    <td>
                        ${log.error_message ? 
                            log.error_message.substring(0, 50) + (log.error_message.length > 50 ? '...' : '') : 
                            '<span class="text-success">Success</span>'
                        }
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-info view-response-btn" 
                                data-log-id="${log.id}"
                                data-bs-toggle="modal" 
                                data-bs-target="#responseModal">
                            View Details
                        </button>
                    </td>
                </tr>
            `).join('');
        })
        .catch(error => {
            console.error('Error loading logs:', error);
            logsTable.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Error loading logs</td></tr>';
        })
        .finally(() => {
            refreshBtn.textContent = originalText;
            refreshBtn.disabled = false;
        });
}

function viewResponseDetails(logId) {
    // Reset modal content first
    resetModalContent();
    
    fetch(`/api/response-log/${logId}`)
        .then(response => response.json())
        .then(logData => {
            // Update modal content
            document.getElementById('detail-url').textContent = logData.request_url || '-';
            document.getElementById('detail-timestamp').textContent = new Date(logData.timestamp).toLocaleString() || '-';
            
            const statusBadge = document.getElementById('detail-status');
            statusBadge.textContent = logData.response_status || 'N/A';
            statusBadge.className = `badge ${logData.response_status === 200 ? 'bg-success' : 'bg-danger'}`;
            
            document.getElementById('detail-added').textContent = logData.participants_added || 0;
            
            const responseBody = logData.response_body ? 
                JSON.stringify(logData.response_body, null, 2) : 
                'No response body';
            document.getElementById('response-details').textContent = responseBody;
        })
        .catch(error => {
            console.error('Error fetching response details:', error);
            document.getElementById('response-details').textContent = 'Error loading response details: ' + error.message;
        });
}

function showNotification(message, type = 'info') {
    // Messages can contain values from uploaded files, so always go through the escaping helper.
    notify(message, type, type === 'error' ? 20000 : 8000);
}

class APIService {
    constructor() {
        this.updateStatus();
        // Update status every 10 seconds
        setInterval(() => this.updateStatus(), 10000);
    }
    
    async updateStatus() {
        try {
            const response = await fetch('/api/api-config/status');
            const status = await response.json();
            
            const statusElement = document.getElementById('api-status');
            const startBtn = document.getElementById('start-api-btn');
            const stopBtn = document.getElementById('stop-api-btn');
            
            if (statusElement) {
                statusElement.textContent = status.is_running ? 'RUNNING' : 'STOPPED';
                statusElement.className = status.is_running ? 'status-running' : 'status-stopped';
            }
            
            if (startBtn) startBtn.disabled = status.is_running;
            if (stopBtn) stopBtn.disabled = !status.is_running;
            
        } catch (error) {
            console.error('Error updating API status:', error);
        }
    }
    
    async startService() {
        let startBtn = document.getElementById('start-api-btn');
        const originalText = startBtn.textContent;
        
        try {
            startBtn.textContent = 'Starting...';
            startBtn.disabled = true;
            
            const response = await fetch('/api/api-config/start', { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();
            
            if (result.success) {
                showNotification(result.message, 'success');
            } else {
                showNotification(result.message, 'error');
            }
            
            // Update status regardless of result
            this.updateStatus();
            
        } catch (error) {
            console.error('Error starting API service:', error);
            showNotification('Error starting API service', 'error');
        } finally {
            // Always reset button state
            startBtn.textContent = originalText;
            startBtn.disabled = false;
            // Force status update to ensure button states are correct
            setTimeout(() => this.updateStatus(), 1000);
        }
    }
    
    async stopService() {
        let stopBtn = document.getElementById('stop-api-btn');
        const originalText = stopBtn.textContent;
        
        try {
            stopBtn.textContent = 'Stopping...';
            stopBtn.disabled = true;
            
            const response = await fetch('/api/api-config/stop', { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();
            
            if (result.success) {
                showNotification(result.message, 'success');
            } else {
                showNotification(result.message, 'error');
            }
            
            // Update status regardless of result
            this.updateStatus();
            
        } catch (error) {
            console.error('Error stopping API service:', error);
            showNotification('Error stopping API service', 'error');
        } finally {
            // Always reset button state
            stopBtn.textContent = originalText;
            stopBtn.disabled = false;
            // Force status update to ensure button states are correct
            setTimeout(() => this.updateStatus(), 1000);
        }
    }
    
    async testConnection() {
        let testBtn = document.getElementById('test-connection-btn') || document.getElementById('test-api');
        const originalText = testBtn.textContent;
        
        try {
            testBtn.textContent = 'Testing...';
            testBtn.disabled = true;
            
            const response = await fetch('/api/api-config/test', { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();
            
            if (result.success) {
                showNotification(result.message, 'success');
            } else {
                showNotification(result.message, 'error');
            }
        } catch (error) {
            console.error('Error testing API connection:', error);
            showNotification('Error testing API connection', 'error');
        } finally {
            // Always reset button state
            testBtn.textContent = originalText;
            testBtn.disabled = false;
        }
    }
}