// Draw control screen: lock → seed → start → pick winners → record call outcomes.
(() => {
    const $ = id => document.getElementById(id);
    const select = $('draw-select');
    let drawId = null;
    let data = null;           // { state, summary }
    let timer = null;
    let busy = false;          // a user action is running; skip background refreshes

    const STAGES = ['entries', 'seed', 'ready', 'live', 'done', 'closed'];

    function showStage(name) {
        STAGES.forEach(s => $(`stage-${s}`).classList.toggle('hidden', s !== name));
    }

    function stepState(id, cls, text) {
        const li = document.querySelector(`#steps li[data-step="${id}"]`);
        li.className = cls;
        $(`step-${id}`).textContent = text;
    }

    function fmtDate(iso) {
        return iso ? new Date(iso).toLocaleString() : '';
    }

    function fact(label, value, extraClass = '') {
        return `<dt>${escapeHtml(label)}</dt><dd class="${extraClass}">${value}</dd>`;
    }

    function outcomePill(w) {
        if (w.status === 'confirmed') return '<span class="pill pill-green">Answered</span>';
        if (w.status === 'void') {
            const why = { no_answer: 'No answer', ineligible: 'Not eligible' }[w.void_reason] || 'Void';
            return `<span class="pill pill-red">${why} · redrawn</span>`;
        }
        return '<span class="pill pill-amber">Awaiting call</span>';
    }

    // ------------------------------------------------------------ rendering

    function render() {
        const { state: st, summary: sm } = data;

        // Steps
        stepState('entries', st.locked ? 'done' : 'current',
            `${sm.numbers} numbers · ${sm.tickets} tickets`);
        stepState('lock', st.locked ? 'done' : '',
            st.locked ? `Locked ${fmtDate(st.locked_at)}` : 'Not locked');
        stepState('seed', st.seeded ? 'done' : (st.locked ? 'current' : ''),
            st.seeded ? (st.seed_source === 'drand' ? 'drand' : 'Manual') : 'No seed');
        stepState('draw', st.status === 'completed' ? 'done' : (st.seeded ? 'current' : ''),
            `${st.winners_drawn} of ${st.total_winners} winners`);

        // Stage panel
        if (st.status === 'cancelled') {
            $('closed-title').textContent = 'This draw was cancelled.';
            showStage('closed');
        } else if (!st.locked) {
            const excluded = Object.entries(sm.excluded)
                .map(([k, v]) => `${v} ${EXCLUSION_LABELS[k] || k}`).join(', ') || 'none';
            $('entry-facts').innerHTML =
                fact('Entries received', sm.entries_total) +
                fact('Not eligible', escapeHtml(excluded)) +
                fact('Rule', escapeHtml(ENTRY_MODE_LABELS[st.entry_mode] || st.entry_mode)) +
                fact('Whitelist', st.whitelist_enabled ? 'On' : 'Off') +
                fact('Tickets in the draw', sm.tickets) +
                fact('Different numbers', sm.numbers) +
                fact('Prizes', st.total_winners);
            $('btn-lock').disabled = sm.numbers < st.total_winners;
            showStage('entries');
        } else if (!st.seeded) {
            $('btn-unlock').classList.toggle('hidden', !window.IS_ADMIN);
            showStage('seed');
        } else if (st.status === 'completed') {
            showStage('done');
        } else if (st.status === 'active') {
            $('next-prize').textContent = st.next_prize ? st.next_prize.name : '-';
            $('live-progress').textContent =
                `${st.winners_drawn} of ${st.total_winners} winners drawn · ${sm.numbers_can_win} numbers can still win`;
            showStage('live');
        } else {
            $('ready-title').textContent = st.winners_drawn ? 'Draw paused' : 'Ready to draw';
            $('ready-text').textContent = st.winners_drawn
                ? 'Resume when the call is finished or the studio is ready.'
                : 'The list is locked and the seed is recorded. Starting makes the draw live on the on-air screen.';
            $('btn-start').textContent = st.winners_drawn ? '▶ Resume draw' : '▶ Start draw';
            showStage('ready');
        }

        renderWinner(sm.winners);
        renderWinners(sm.winners);
        renderRecord(st, sm);
    }

    function renderWinner(winners) {
        const w = winners[winners.length - 1];
        $('winner-empty').classList.toggle('hidden', !!w);
        $('winner-body').classList.toggle('hidden', !w);
        if (!w) return;
        $('w-prize').textContent = `Winner ${w.position} · ${w.prize}`;
        $('w-phone').textContent = w.phone_local;
        $('w-name').textContent = w.name || 'Name not provided';
        $('w-status').innerHTML = outcomePill(w);
        $('w-actions').classList.toggle('hidden', w.status !== 'drawn');
        $('w-actions').dataset.winnerId = w.id;
        $('winner-card').classList.toggle('needs-call', w.status === 'drawn');
    }

    function renderWinners(winners) {
        const body = $('winners-table');
        if (!winners.length) {
            body.innerHTML = '<tr><td colspan="6" class="muted">None yet</td></tr>';
            return;
        }
        body.innerHTML = winners.map(w => `
            <tr class="${w.status === 'void' ? 'void' : ''}">
                <td>${w.position}</td>
                <td>${escapeHtml(w.prize)}</td>
                <td class="mono">${escapeHtml(w.phone_local)}</td>
                <td>${escapeHtml(w.name || '')}</td>
                <td>${outcomePill(w)}</td>
                <td>${w.status !== 'void'
                    ? `<button class="btn btn-sm btn-danger" data-void="${w.id}">Void</button>` : ''}</td>
            </tr>`).join('');
    }

    function renderRecord(st, sm) {
        $('record-facts').innerHTML =
            fact('Entry rule', escapeHtml(ENTRY_MODE_LABELS[st.entry_mode] || st.entry_mode)) +
            fact('Locked at', st.locked ? escapeHtml(fmtDate(st.locked_at)) : 'Not locked') +
            fact('Tickets locked', st.pool_size ?? '-') +
            fact('List fingerprint', st.pool_fingerprint ? escapeHtml(st.pool_fingerprint) : '-', 'mono') +
            fact('Seed', sm.seed ? escapeHtml(sm.seed) : '-', 'mono') +
            fact('Seed source', st.seed_reference ? escapeHtml(st.seed_reference) : '-');
        $('btn-replay').disabled = !st.seeded;
    }

    // ------------------------------------------------------------ loading

    async function refresh() {
        if (!drawId || busy) return;
        try {
            data = await api(`/api/draws/${drawId}/summary`);
            render();
        } catch (e) {
            notify(e.message, 'error');
        }
    }

    function selectDraw(id) {
        drawId = id ? Number(id) : null;
        clearInterval(timer);
        $('no-draw').classList.toggle('hidden', !!drawId);
        $('control').classList.toggle('hidden', !drawId);
        $('open-on-air').classList.toggle('hidden', !drawId);
        $('replay-result').classList.add('hidden');
        if (!drawId) return;
        $('open-on-air').href = `/tv/${drawId}`;
        history.replaceState(null, '', `?draw=${drawId}`);
        refresh();
        timer = setInterval(refresh, 3000);  // picks up API entries and other operators' actions
    }

    /** Run an action that returns {state}; then reload the summary. */
    async function act(button, busyText, fn) {
        busy = true;
        try {
            await withButton(button, fn, busyText);
        } finally {
            busy = false;
            await refresh();
        }
    }

    // ------------------------------------------------------------ actions

    $('btn-lock').onclick = e => {
        const st = data.state, sm = data.summary;
        if (!confirm(`Lock the entry list now?\n\n${sm.tickets} tickets from ${sm.numbers} numbers for ` +
                     `${st.total_winners} prizes.\n\nAfter locking nothing about the entries, prizes or rules can change.`)) return;
        act(e.currentTarget, 'Locking…', async () => {
            await api(`/api/draws/${drawId}/lock`, { method: 'POST' });
            notify('Entry list locked. Take the seed next.', 'success');
        });
    };

    $('btn-unlock').onclick = e => {
        if (!confirm('Unlock the entry list? Only do this if it was locked by mistake.')) return;
        act(e.currentTarget, 'Unlocking…', () => api(`/api/draws/${drawId}/unlock`, { method: 'POST' }));
    };

    $('btn-drand').onclick = e => act(e.currentTarget, 'Waiting for the drand round…', async () => {
        await api(`/api/draws/${drawId}/seed/drand`, { method: 'POST' });
        notify('drand seed recorded.', 'success');
    });

    $('manual-seed').onsubmit = e => {
        e.preventDefault();
        const seed = $('seed-value').value.trim();
        const reference = $('seed-reference').value.trim();
        if (!confirm(`Use "${seed}" as the seed? It can never be changed.`)) return;
        act(e.submitter, 'Saving…', async () => {
            await api(`/api/draws/${drawId}/seed/manual`, { method: 'POST', body: { seed, reference } });
            $('seed-value').value = '';
            notify('Manual seed recorded.', 'success');
        });
    };

    $('btn-start').onclick = e => act(e.currentTarget, 'Starting…',
        () => api(`/api/draws/${drawId}/start`, { method: 'POST' }));

    $('btn-pause').onclick = e => act(e.currentTarget, 'Pausing…',
        () => api(`/api/draws/${drawId}/stop`, { method: 'POST' }));

    $('btn-pick').onclick = e => {
        const pending = data.summary.winners.find(w => w.status === 'drawn');
        if (pending && !confirm(`Winner ${pending.position} (${pending.phone_local}) has no call outcome yet. Pick the next winner anyway?`)) return;
        act(e.currentTarget, 'Drawing…', async () => {
            const r = await api(`/api/draws/${drawId}/draw-winner`, { method: 'POST' });
            notify(`Winner ${r.winner.position}: ${r.winner.prize.name}`, 'success');
        });
    };

    async function recordOutcome(winnerId, outcome, button) {
        if (outcome === 'confirm') {
            return act(button, 'Saving…',
                () => api(`/api/winners/${winnerId}/confirm`, { method: 'POST' }));
        }
        const label = outcome === 'no_answer' ? 'did not answer' : 'is not eligible';
        if (!confirm(`Void this winner because they ${label}?\n\nThe same prize will be drawn again.`)) return;
        return act(button, 'Saving…',
            () => api(`/api/winners/${winnerId}/void`, { method: 'POST', body: { reason: outcome } }));
    }

    $('w-actions').onclick = e => {
        const b = e.target.closest('button[data-outcome]');
        if (b) recordOutcome($('w-actions').dataset.winnerId, b.dataset.outcome, b);
    };

    $('winners-table').onclick = e => {
        const b = e.target.closest('button[data-void]');
        if (!b) return;
        const reason = prompt('Why is this winner void? Type: no_answer, ineligible or other', 'ineligible');
        if (!reason) return;
        act(b, '…', () => api(`/api/winners/${b.dataset.void}/void`, { method: 'POST', body: { reason: reason.trim() } }));
    };

    $('btn-replay').onclick = e => act(e.currentTarget, 'Checking…', async () => {
        const { replay: r } = await api(`/api/draws/${drawId}/replay`);
        const box = $('replay-result');
        box.className = `replay ${r.all_ok ? 'ok' : 'bad'}`;
        const rows = r.picks.map(p =>
            `<li>Winner ${p.position}: ${p.ok ? '✅ matches' : `❌ expected entry ${p.expected_entry}, recorded ${p.recorded_entry}`}</li>`
        ).join('');
        box.innerHTML = `<strong>${r.all_ok ? '✅ The draw replays exactly.' : '❌ The draw does NOT replay. Stop and investigate.'}</strong>
            <p>Fingerprint ${r.fingerprint_ok ? 'matches the locked list' : 'does NOT match: the entries changed after locking'}.</p>
            <ul>${rows || '<li>No winners yet</li>'}</ul>`;
    });

    select.onchange = () => selectDraw(select.value);

    const initial = new URLSearchParams(location.search).get('draw');
    if (initial && [...select.options].some(o => o.value === initial)) {
        select.value = initial;
        selectDraw(initial);
    }
})();
