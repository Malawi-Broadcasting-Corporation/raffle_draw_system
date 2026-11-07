// On-air screen. Display only: it follows the draw state and never changes anything.
(() => {
    const cfg = window.TV_CONFIG || {};
    const $ = id => document.getElementById(id);
    const POLL_MS = 1000;
    const SPIN_MS = 4500;
    const RESULTS_AFTER_MS = 10000;   // after the final reveal, switch to the results board

    let drawId = cfg.drawId;
    let seenPosition = null;          // highest winner position already shown
    let shown = null;                 // winner currently on the number display
    let spinning = false;
    let lastRevealAt = 0;
    let latest = null;                // last state received

    // ------------------------------------------------------------ fit 1920x1080 to the output
    function fit() {
        const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
        const stage = $('stage');
        stage.style.transform = `scale(${s})`;
        stage.style.left = `${(window.innerWidth - 1920 * s) / 2}px`;
        stage.style.top = `${(window.innerHeight - 1080 * s) / 2}px`;
    }
    window.addEventListener('resize', fit);
    fit();

    // ------------------------------------------------------------ helpers
    const show = (id, on) => $(id).classList.toggle('hidden', !on);
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function proofLine(st) {
        if (!st.locked) return st.status === 'draft' ? 'Entries are still open' : '';
        const fp = st.pool_fingerprint || '';
        const time = new Date(st.locked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        let line = `${Number(st.pool_size).toLocaleString()} entries · List locked ${time} · Fingerprint ${fp.slice(0, 8)}…${fp.slice(-4)}`;
        if (st.seeded) line += st.seed_source === 'drand' ? ' · Seed: drand public randomness' : ' · Seed: drawn on air';
        return line;
    }

    function confetti() {
        const box = $('confetti');
        const colours = ['#DE232A', '#02964E', '#ffffff', '#941C26', '#000000'];
        for (let i = 0; i < 140; i++) {
            const p = document.createElement('div');
            p.className = 'confetti-piece';
            p.style.left = `${Math.random() * 1920}px`;
            p.style.background = colours[i % colours.length];
            p.style.animationDuration = `${2.5 + Math.random() * 2.5}s`;
            p.style.animationDelay = `${Math.random() * 0.8}s`;
            box.appendChild(p);
            setTimeout(() => p.remove(), 6000);
        }
    }

    // ------------------------------------------------------------ spin and reveal
    async function spinTo(winner) {
        spinning = true;
        const number = $('number');
        number.className = 'number spinning';
        $('prize-label').innerHTML = `NOW DRAWING <strong>${esc(winner.prize)}</strong>`;
        $('caption').textContent = '';
        show('notice', false);

        let pool = [];
        try {
            const r = await fetch(`/api/draws/${drawId}/animation`).then(res => res.json());
            pool = r.sequence || [];
        } catch (e) { /* spin on the winner's own mask */ }
        if (!pool.length) pool = [winner.phone_masked];

        const start = performance.now();
        let i = 0;
        while (performance.now() - start < SPIN_MS) {
            const t = (performance.now() - start) / SPIN_MS;      // 0..1, slows down towards the end
            number.textContent = pool[i++ % pool.length];
            await sleep(40 + 320 * t * t);
        }

        number.textContent = winner.phone_masked;
        number.className = 'number revealed';
        shown = winner;
        lastRevealAt = Date.now();
        spinning = false;
        confetti();
        if (latest) render(latest);
    }

    // ------------------------------------------------------------ render
    function renderIdle() {
        $('stage').classList.add('is-idle');
        show('idle', true);
        ['title-bar', 'main', 'results', 'winners-panel'].forEach(id => show(id, false));
        $('proof').textContent = '';
    }

    function renderWinnersPanel(winners) {
        show('winners-panel', winners.length > 0);
        $('winners-list').innerHTML = winners.slice(-8).map(w => `
            <li class="${w.status === 'void' ? 'void' : ''}">
                <span class="ph">${esc(w.phone_masked)}${w.status === 'confirmed' ? '<span class="tick">✓</span>' : ''}</span>
                <span class="pz">${esc(w.prize)}${w.status === 'void' ? ' · redrawn' : ''}</span>
            </li>`).join('');
    }

    function renderResults(winners) {
        const valid = winners.filter(w => w.status !== 'void');
        $('results').classList.toggle('many', valid.length > 8);
        $('results-list').innerHTML = valid.map(w => `
            <li><span class="pz">${esc(w.prize)}</span><span class="ph">${esc(w.phone_masked)}</span></li>`).join('');
    }

    function render(st) {
        if (!st) { renderIdle(); return; }
        $('stage').classList.remove('is-idle');
        show('idle', false);
        show('title-bar', true);
        $('draw-title').textContent = st.name;
        const live = $('live-tag');
        live.textContent = st.status === 'completed' ? 'RESULTS' : (st.locked ? 'LIVE' : 'COMING UP');
        live.classList.toggle('off', !st.locked);
        $('proof').textContent = proofLine(st);

        const winners = st.winners || [];
        const newest = winners[winners.length - 1];
        if (seenPosition === null) {
            // First load: show the current situation without replaying old reveals.
            seenPosition = newest ? newest.position : 0;
            shown = newest || null;
        }
        if (spinning) return;
        if (newest && newest.position > seenPosition) {
            seenPosition = newest.position;
            spinTo(newest);
            return;
        }
        // Keep the shown winner's status (confirmed / void) up to date.
        if (shown) shown = winners.find(w => w.id === shown.id) || shown;

        const showResults = st.status === 'completed' && Date.now() - lastRevealAt > RESULTS_AFTER_MS;
        show('results', showResults);
        show('main', !showResults);
        if (showResults) {
            renderResults(winners);
            show('winners-panel', false);
            return;
        }
        renderWinnersPanel(winners);

        const number = $('number');
        const notice = $('notice');
        if (shown) {
            number.textContent = shown.phone_masked;
            if (!number.classList.contains('revealed')) number.className = 'number';
            const nth = winners.filter(w => w.status !== 'void' && w.position <= shown.position).length;
            $('prize-label').innerHTML = `WINNER <strong>${esc(shown.prize)}</strong>`;
            $('caption').textContent = shown.status === 'void' ? '' : `Winner ${nth} of ${st.total_winners}`;
            if (shown.status === 'confirmed') {
                notice.textContent = '✓ Winner confirmed';
                notice.className = 'notice good';
            } else if (shown.status === 'void') {
                notice.textContent = shown.void_reason === 'no_answer'
                    ? 'We could not reach this winner · the prize will be drawn again'
                    : 'This entry is not eligible · the prize will be drawn again';
                notice.className = 'notice';
            } else {
                notice.textContent = 'Calling the winner now…';
                notice.className = 'notice';
            }
            show('notice', true);
        } else {
            number.textContent = 'READY';
            number.className = 'number idle-word';
            $('prize-label').innerHTML = st.next_prize ? `NOW DRAWING <strong>${esc(st.next_prize.name)}</strong>` : '';
            $('caption').textContent = st.locked ? `${st.total_winners} prizes to be won` : '';
            show('notice', false);
        }
    }

    // ------------------------------------------------------------ polling
    async function poll() {
        try {
            const url = cfg.pinned ? `/api/draws/${drawId}/state` : '/api/draws/live';
            const r = await fetch(url, { cache: 'no-store' }).then(res => res.json());
            const st = r.success ? r.state : null;
            if (!cfg.pinned && st && st.draw_id !== drawId) {
                // Followed draw changed: start fresh without replaying its old reveals.
                drawId = st.draw_id;
                seenPosition = null;
                shown = null;
            }
            latest = st;
            render(st);
        } catch (e) {
            // Network hiccup: keep the last frame on air rather than flashing an error.
        } finally {
            setTimeout(poll, POLL_MS);
        }
    }
    poll();
})();
