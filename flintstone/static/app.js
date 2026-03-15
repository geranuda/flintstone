/* Flintstone - minimal UI enhancements */

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

// Keyboard shortcut: Ctrl+S to save focused translation
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        const active = document.activeElement;
        if (active && active.dataset && active.dataset.keyId) {
            active.dispatchEvent(new Event('change'));
        }
    }
});
