/* Flintstone - minimal UI enhancements */

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

// Inline "value + Copy button" markup used for tokens and secrets.
function copyable(value) {
    return `<span class="copyable"><code>${escapeHtml(value)}</code>` +
        `<button type="button" class="copy-btn outline secondary" data-copy-value="${escapeHtml(value)}">Copy</button></span>`;
}

async function copyText(text, button) {
    try {
        await navigator.clipboard.writeText(text);
    } catch (e) {
        const area = document.createElement('textarea');
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
    }
    if (button) {
        const label = button.textContent;
        button.textContent = 'Copied';
        setTimeout(() => { button.textContent = label; }, 1200);
    }
}

document.addEventListener('click', function(e) {
    const button = e.target.closest('[data-copy], [data-copy-value]');
    if (!button) return;
    e.preventDefault();
    const text = button.dataset.copyValue ?? document.querySelector(button.dataset.copy)?.textContent ?? '';
    copyText(text.trim(), button);
});

// Flash message helper
function showFlash(message, type) {
    const container = document.getElementById('flash-container');
    if (!container) return;
    const div = document.createElement('div');
    div.className = `flash flash-${type}`;
    div.textContent = message;
    container.appendChild(div);
    setTimeout(() => div.remove(), 5000);
}

// Keyboard shortcut: Ctrl+S to save the focused translation
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        const active = document.activeElement;
        if (active && (active.dataset?.keyId || active.closest?.('.string-row'))) {
            active.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
});
