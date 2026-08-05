// Confirmación antes de eliminar
document.querySelectorAll('[data-confirm]').forEach(btn => {
    btn.addEventListener('click', e => {
        if (!confirm(btn.dataset.confirm || '¿Estás seguro?')) {
            e.preventDefault();
        }
    });
});

// Auto-cerrar mensajes de alerta
setTimeout(() => {
    document.querySelectorAll('[data-autohide]').forEach(el => {
        el.style.transition = 'opacity 0.5s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
    });
}, 4000);