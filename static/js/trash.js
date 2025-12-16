function bulkRestore() {
    const ids = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!ids.length) return alert('Выберите файлы');

    const container = document.getElementById('bulkRestoreFiles');
    const form = document.getElementById('bulkRestoreForm');
    if (!container || !form) return;

    container.innerHTML = ids
        .map(id => `<input type="hidden" name="file_ids" value="${id}">`)
        .join('');

    form.submit();
}

function bulkDeletePermanent() {
    const ids = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!ids.length) return alert('Выберите файлы');

    if (!confirm(`Удалить навсегда ${ids.length} файл(ов)?`)) return;

    const container = document.getElementById('bulkDeleteFiles');
    const form = document.getElementById('bulkDeleteForm');
    if (!container || !form) return;

    container.innerHTML = ids
        .map(id => `<input type="hidden" name="file_ids" value="${id}">`)
        .join('');

    form.submit();
}

window.bulkRestore = bulkRestore;
window.bulkDeletePermanent = bulkDeletePermanent;
