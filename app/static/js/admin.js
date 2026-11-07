// Draw management: create draws with prizes and rules; whitelist upload per draw.
(() => {
    const $ = id => document.getElementById(id);
    const rows = $('prize-rows');

    function addPrizeRow(prize = {}) {
        const row = document.createElement('div');
        row.className = 'prize-row';
        row.innerHTML = `
            <input class="form-control p-name" placeholder="e.g. 55-inch TV" required maxlength="150" value="${escapeHtml(prize.name || '')}">
            <select class="form-control p-type">
                <option value="cash">Cash</option><option value="goods">Goods</option>
                <option value="voucher">Voucher</option><option value="service">Service</option>
            </select>
            <input class="form-control p-qty" type="number" min="1" value="${prize.quantity || 1}" required>
            <input class="form-control p-value" type="number" min="0" step="any" placeholder="-">
            <button type="button" class="remove-prize" title="Remove prize" aria-label="Remove prize">&times;</button>`;
        row.querySelector('.p-type').value = prize.prize_type || 'cash';
        row.querySelector('.remove-prize').onclick = () => {
            if (rows.children.length > 1) row.remove();
        };
        rows.appendChild(row);
    }

    $('add-prize').onclick = () => addPrizeRow();
    addPrizeRow();

    $('create-draw-form').onsubmit = e => {
        e.preventDefault();
        const prizes = [...rows.children].map((row, i) => ({
            name: row.querySelector('.p-name').value.trim(),
            prize_type: row.querySelector('.p-type').value,
            quantity: Number(row.querySelector('.p-qty').value),
            value: row.querySelector('.p-value').value || null,
            draw_order: i,
        }));
        const body = {
            name: $('draw-name').value.trim(),
            description: $('draw-description').value.trim(),
            entry_mode: $('entry-mode').value,
            whitelist_enabled: $('whitelist-enabled').checked,
            prizes,
        };
        withButton(e.submitter, async () => {
            await api('/admin/draws', { method: 'POST', body });
            notify('Draw created', 'success');
            setTimeout(() => location.reload(), 800);
        }, 'Creating…');
    };

    // ------------------------------------------------------------ per-draw actions
    $('draws-table').addEventListener('click', e => {
        const b = e.target.closest('button[data-action]');
        if (!b) return;
        const tr = b.closest('tr');
        const id = tr.dataset.id;
        const name = tr.querySelector('strong').textContent;

        if (b.dataset.action === 'delete') {
            if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
            withButton(b, async () => {
                await api(`/admin/draws/${id}`, { method: 'DELETE' });
                tr.remove();
                notify('Draw deleted', 'success');
            });
        }

        if (b.dataset.action === 'mode') {
            const current = tr.querySelector('.rules-cell').dataset.mode;
            const next = current === 'per_sms' ? 'per_number' : 'per_sms';
            if (!confirm(`Change "${name}" to: ${ENTRY_MODE_LABELS[next]}?`)) return;
            withButton(b, async () => {
                await api(`/admin/draws/${id}/rules`, { method: 'PATCH', body: { entry_mode: next } });
                location.reload();
            });
        }

        if (b.dataset.action === 'clear-whitelist') {
            if (!confirm(`Remove the whitelist from "${name}"? Everyone who entered can then win.`)) return;
            withButton(b, async () => {
                await api(`/admin/draws/${id}/whitelist`, { method: 'DELETE' });
                location.reload();
            });
        }
    });

    $('draws-table').addEventListener('change', async e => {
        const input = e.target.closest('input[data-action="whitelist"]');
        if (!input || !input.files.length) return;
        const tr = input.closest('tr');
        const form = new FormData();
        form.append('file', input.files[0]);
        try {
            const r = await api(`/admin/draws/${tr.dataset.id}/whitelist`, { method: 'POST', form });
            let msg = `${r.message}. ${r.entries_excluded} existing entries are now not eligible.`;
            if (r.problems && r.problems.length) {
                msg += ' Rejected rows: ' + r.problems.slice(0, 5).map(p => `row ${p.line} (${p.reason})`).join('; ');
            }
            notify(msg, 'success', 15000);
            setTimeout(() => location.reload(), 2500);
        } catch (err) {
            notify(err.message, 'error', 20000);
        } finally {
            input.value = '';
        }
    });
})();
