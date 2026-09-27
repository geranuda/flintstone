/* Translation editor: autosave, plural forms, review status, character limits, TM suggestions */
(function () {
    const list = document.getElementById('strings');
    if (!list) return;

    const targetId = list.dataset.targetId;
    const targetCode = list.dataset.targetCode;
    const sourceCode = list.dataset.sourceCode;
    const PLURAL_ORDER = ['zero', 'one', 'two', 'few', 'many', 'other'];
    const STATUS_LABELS = { untranslated: 'Untranslated', translated: 'Translated', reviewed: 'Reviewed', proofread: 'Proofread' };

    const rows = () => [...list.querySelectorAll('.string-row')];
    const inputsOf = row => [...row.querySelectorAll('textarea')];

    function autosize(area) {
        area.style.height = 'auto';
        area.style.height = (area.scrollHeight + 2) + 'px';
    }

    function escapeXml(value) {
        return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // Serialize the row's inputs the way the CDS stores them (plain / ICU plural / cds-root XML).
    function buildValue(row) {
        const kind = row.dataset.kind;
        if (kind === 'plural') {
            const forms = {};
            row.querySelectorAll('textarea[data-form]').forEach(a => { forms[a.dataset.form] = a.value; });
            if (!Object.values(forms).some(v => v !== '')) return '';
            if (!forms.other) return null;  // ICU requires the "other" form
            const exact = Object.keys(forms).filter(k => k.startsWith('='))
                .sort((a, b) => parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10));
            const keys = exact.concat(PLURAL_ORDER.filter(c => c in forms)).filter(k => forms[k] !== '');
            return `{${row.dataset.variable || 'cnt'}, plural, ${keys.map(k => `${k} {${forms[k]}}`).join(' ')}}`;
        }
        if (kind === 'variations') {
            const units = [...row.querySelectorAll('textarea[data-unit]')];
            if (!units.some(a => a.value !== '')) return '';
            return '<cds-root>' + units.map(a =>
                `<cds-unit id="${escapeXml(a.dataset.unit).replace(/"/g, '&quot;')}">${escapeXml(a.value)}</cds-unit>`
            ).join('') + '</cds-root>';
        }
        return row.querySelector('textarea[data-single]').value;
    }

    function setState(row, cls, text) {
        const el = row.querySelector('[data-save-state]');
        el.className = 'save-state' + (cls ? ' ' + cls : '');
        el.textContent = text;
        if (cls === 'ok') setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 1800);
    }

    function setStatus(row, status) {
        row.dataset.status = status;
        const label = row.querySelector('[data-status-label]');
        label.className = 'status ' + status;
        label.textContent = STATUS_LABELS[status] || status;
        const review = row.querySelector('[data-review]');
        review.disabled = status === 'untranslated';
        review.classList.toggle('on', status === 'reviewed' || status === 'proofread');
    }

    function updateCount(row) {
        const counter = row.querySelector('[data-char-count]');
        if (!counter) return;
        const limit = parseInt(row.dataset.limit, 10);
        const length = Math.max(0, ...inputsOf(row).map(a => [...a.value].length));
        counter.textContent = `${length}/${limit}`;
        counter.classList.toggle('over', length > limit);
    }

    async function save(row) {
        const value = buildValue(row);
        if (value === null) {
            setState(row, 'err', 'Fill "other"');
            return;
        }
        if (value === row.dataset.saved) return;
        const url = `/api/translations/${row.dataset.keyId}/${targetId}`;
        setState(row, '', 'Saving…');
        let ok;
        try {
            if (value === '') {
                const res = await fetch(url, { method: 'DELETE' });
                ok = res.ok || res.status === 404;
            } else {
                const res = await fetch(url, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value })
                });
                ok = res.ok;
            }
        } catch (e) {
            ok = false;
        }
        if (!ok) {
            setState(row, 'err', 'Not saved');
            return;
        }
        row.dataset.saved = value;
        setStatus(row, value === '' ? 'untranslated' : 'translated');
        setState(row, 'ok', 'Saved');
    }

    async function toggleReview(row, button) {
        const status = button.classList.contains('on') ? 'translated' : 'reviewed';
        const res = await fetch(`/api/translations/${row.dataset.keyId}/${targetId}/status`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status })
        });
        if (res.ok) {
            setStatus(row, status);
            setState(row, 'ok', status === 'reviewed' ? 'Reviewed' : 'Unreviewed');
        } else {
            setState(row, 'err', 'Error');
        }
    }

    // --- Translation memory suggestions (plain strings) ---
    let tmTimer = null;
    let dropdown = null;

    function hideSuggestions() {
        if (dropdown) { dropdown.remove(); dropdown = null; }
    }

    function suggest(row, area) {
        const source = row.querySelector('[data-source-text]');
        if (!source || !area.hasAttribute('data-single')) return;
        clearTimeout(tmTimer);
        tmTimer = setTimeout(async () => {
            const params = new URLSearchParams({
                source: source.dataset.sourceText, source_lang: sourceCode, target_lang: targetCode, limit: '5'
            });
            const res = await fetch(`/api/memory/suggest?${params}`);
            if (!res.ok || document.activeElement !== area) return;
            const items = (await res.json()).filter(s => s.target_text !== area.value);
            if (!items.length) return;
            hideSuggestions();
            dropdown = document.createElement('div');
            dropdown.className = 'tm-dropdown';
            for (const s of items) {
                const item = document.createElement('div');
                item.innerHTML = `${escapeHtml(s.target_text)}<span class="tm-match-type">${escapeHtml(s.match_type)}</span>` +
                    `<br><span class="tm-source">${escapeHtml(s.source_text)}</span>`;
                item.addEventListener('mousedown', e => {
                    e.preventDefault();
                    area.value = s.target_text;
                    autosize(area);
                    updateCount(row);
                    hideSuggestions();
                    save(row);
                });
                dropdown.appendChild(item);
            }
            area.closest('.string-target').appendChild(dropdown);
        }, 250);
    }

    // --- Wiring ---
    rows().forEach(row => {
        row.dataset.saved = buildValue(row) ?? '';
        inputsOf(row).forEach(autosize);
    });

    list.addEventListener('input', e => {
        if (e.target.tagName !== 'TEXTAREA') return;
        const row = e.target.closest('.string-row');
        autosize(e.target);
        updateCount(row);
        hideSuggestions();
    });

    list.addEventListener('change', e => {
        const row = e.target.closest('.string-row');
        if (row && e.target.tagName === 'TEXTAREA') save(row);
    });

    list.addEventListener('focusin', e => {
        const row = e.target.closest('.string-row');
        if (!row) return;
        rows().forEach(r => r.classList.toggle('is-focused', r === row));
        if (e.target.tagName === 'TEXTAREA') suggest(row, e.target);
    });

    list.addEventListener('focusout', () => setTimeout(hideSuggestions, 150));

    list.addEventListener('click', e => {
        const button = e.target.closest('[data-review]');
        if (button) toggleReview(button.closest('.string-row'), button);
    });

    // Cmd/Ctrl+Enter: save and jump to the next string
    list.addEventListener('keydown', e => {
        if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey) || e.target.tagName !== 'TEXTAREA') return;
        e.preventDefault();
        const row = e.target.closest('.string-row');
        save(row);
        const next = row.nextElementSibling?.querySelector('textarea');
        if (next) next.focus();
    });
})();
