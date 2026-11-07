// Shared helpers for the staff pages (not used by the on-air screen).

/** fetch JSON; throws Error(message) when the server says success: false or the request fails. */
async function api(url, { method = 'GET', body, form } = {}) {
    const opts = { method, headers: {} };
    if (form) {
        opts.body = form;
    } else if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    let res;
    try {
        res = await fetch(url, opts);
    } catch (e) {
        throw new Error('Cannot reach the server. Check the connection.');
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok || (data && data.success === false)) {
        throw new Error((data && data.message) || `Request failed (${res.status})`);
    }
    return data;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function notify(message, type = 'info', timeout = 6000) {
    let box = document.getElementById('notify-box');
    if (!box) {
        box = document.createElement('div');
        box.id = 'notify-box';
        document.body.appendChild(box);
    }
    const el = document.createElement('div');
    el.className = `notify notify-${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.innerHTML = `<span>${escapeHtml(message)}</span><button aria-label="Close">&times;</button>`;
    el.querySelector('button').onclick = () => el.remove();
    box.appendChild(el);
    if (timeout) setTimeout(() => el.remove(), timeout);
}

/** Run an async action from a button: disables it while running and reports errors. */
async function withButton(button, action, busyText) {
    const original = button.innerHTML;
    button.disabled = true;
    if (busyText) button.innerHTML = escapeHtml(busyText);
    try {
        return await action();
    } catch (e) {
        notify(e.message, 'error', 10000);
    } finally {
        button.disabled = false;
        button.innerHTML = original;
    }
}

const ENTRY_MODE_LABELS = {
    per_sms: 'One entry per SMS',
    per_number: 'One entry per number',
};

const EXCLUSION_LABELS = {
    not_on_whitelist: 'Not on whitelist',
    received_after_lock: 'Arrived after lock',
};
