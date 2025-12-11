// ==================== ВЫДЕЛЕНИЕ ФАЙЛОВ ====================

function updateSelection() {
    const checkboxes = document.querySelectorAll('.file-checkbox:checked');
    const count = checkboxes.length;
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');
    const selectAll = document.getElementById('selectAll');
    const allCheckboxes = document.querySelectorAll('.file-checkbox');

    if (selectedCount) selectedCount.textContent = count;

    if (bulkActions) {
        bulkActions.style.display = count > 0 ? 'flex' : 'none';
    }

    if (selectAll) {
        selectAll.checked = allCheckboxes.length > 0 && count === allCheckboxes.length;
        selectAll.indeterminate = count > 0 && count < allCheckboxes.length;
    }

    document.querySelectorAll('.file-card').forEach(card => {
        const checkbox = card.querySelector('.file-checkbox');
        if (checkbox && checkbox.checked) card.classList.add('selected');
        else card.classList.remove('selected');
    });
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.file-checkbox');
    if (!selectAll) return;

    checkboxes.forEach(checkbox => {
        checkbox.checked = selectAll.checked;
    });

    updateSelection();
}

function clearSelection() {
    document.querySelectorAll('.file-checkbox').forEach(checkbox => {
        checkbox.checked = false;
    });
    const selectAll = document.getElementById('selectAll');
    if (selectAll) selectAll.checked = false;
    updateSelection();
}

function getSelectedIds() {
    const checkboxes = document.querySelectorAll('.file-checkbox:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

// ==================== МАССОВЫЕ ОПЕРАЦИИ ====================

function bulkDelete(deleteType) {
    const ids = getSelectedIds();
    if (ids.length === 0) {
        alert('Выберите файлы для удаления');
        return;
    }

    const actionText = deleteType === 'permanent' ? 'удалить навсегда' : 'переместить в корзину';
    if (!confirm(`Вы уверены, что хотите ${actionText} ${ids.length} файл(ов)?`)) {
        return;
    }

    const typeInput = document.getElementById('bulkDeleteType');
    const container = document.getElementById('bulkDeleteFiles');
    const form = document.getElementById('bulkDeleteForm');
    if (!typeInput || !container || !form) return;

    typeInput.value = deleteType;
    container.innerHTML = '';

    ids.forEach(id => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'file_ids';
        input.value = id;
        container.appendChild(input);
    });

    form.submit();
}

function bulkDownload() {
    const ids = getSelectedIds();
    if (ids.length === 0) {
        alert('Выберите файлы для скачивания');
        return;
    }

    const container = document.getElementById('bulkDownloadFiles');
    const form = document.getElementById('bulkDownloadForm');
    if (!container || !form) return;

    container.innerHTML = '';

    ids.forEach(id => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'file_ids';
        input.value = id;
        container.appendChild(input);
    });

    form.submit();
}

// ==================== МОДАЛЬНЫЕ ОКНА ====================

function openRenameModal(fileId, fileName) {
    const form = document.getElementById('renameForm');
    const input = document.getElementById('new_name');
    const modal = document.getElementById('renameModal');
    if (!form || !input || !modal) return;

    form.action = `/rename/${fileId}`;
    input.value = fileName;
    modal.classList.add('active');
}

function openDeleteModal(fileId, fileName) {
    const form = document.getElementById('deleteForm');
    const nameSpan = document.getElementById('deleteFileName');
    const modal = document.getElementById('deleteModal');
    if (!form || !nameSpan || !modal) return;

    form.action = `/delete/${fileId}`;
    nameSpan.textContent = fileName;
    modal.classList.add('active');
}

// Закрытие модальных окон по клику по фону
document.addEventListener('click', e => {
    const modal = e.target.closest('.modal');
    if (!modal) return;
    if (e.target === modal) modal.classList.remove('active');
});

// ==================== DRAG & DROP (ПРОСТО И РАБОТАЕТ) ====================

const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');

if (uploadArea && fileInput) {
    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', e => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', e => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        fileInput.files = e.dataTransfer.files;
        updateFileList();
        // НИЧЕГО больше не трогаем
    });
}

if (fileInput) {
    fileInput.addEventListener('change', () => {
        updateFileList();
        // НЕ сбрасываем value
    });
}

function updateFileList() {
    if (!fileList || !fileInput) return;
    fileList.innerHTML = '';
    for (let file of fileInput.files) {
        const item = document.createElement('div');
        item.className = 'file-list-item';
        item.innerHTML = `
            <i class="fas fa-file"></i>
            <span>${file.name}</span>
            <span class="file-size">${formatSize(file.size)}</span>
        `;
        fileList.appendChild(item);
    }
}

function formatSize(bytes) {
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return bytes.toFixed(2) + ' ' + units[i];
}


// ==================== ПЕРЕМЕЩЕНИЕ / КОПИРОВАНИЕ ====================

function openMoveModal() {
    const ids = getSelectedIds();
    if (ids.length === 0) return alert('Выберите файлы');

    const modal = document.getElementById('moveModal');
    if (!modal) return;

    modal.classList.add('active');
    loadFolders();
}

async function loadFolders() {
    const list = document.getElementById('folderList');
    if (!list) return;

    try {
        const response = await fetch('/get_folders_tree');
        const folders = await response.json();

        list.innerHTML = '';

        if (!folders.length) {
            list.innerHTML = '<p style="font-size: 0.8rem; color: gray; padding: 0.5rem;">Нет других папок</p>';
            return;
        }

        folders.forEach(f => {
            const item = document.createElement('label');
            item.className = 'folder-option';
            item.innerHTML = `
                <input type="radio" name="target_folder" value="${f.id}">
                <span class="folder-icon"><i class="fas fa-folder"></i></span>
                <span class="folder-name" style="margin-left: ${f.parent_id ? '20px' : '0'}">${f.name}</span>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        list.innerHTML = '<p style="color: red;">Ошибка загрузки</p>';
    }
}

function submitMoveCopy(action) {
    const selected = document.querySelector('input[name="target_folder"]:checked');
    if (!selected) return alert('Выберите папку назначения');

    const targetId = selected.value;
    const fileIds = getSelectedIds();
    if (!fileIds.length) return alert('Не выбраны файлы');

    const actionInput = document.getElementById('mc_action');
    const targetInput = document.getElementById('mc_target_id');
    const container = document.getElementById('mc_files_container');
    const form = document.getElementById('moveCopyForm');
    if (!actionInput || !targetInput || !container || !form) return;

    actionInput.value = action;
    targetInput.value = targetId;

    container.innerHTML = fileIds
        .map(id => `<input type="hidden" name="file_ids" value="${id}">`)
        .join('');

    form.submit();
}

// ==================== ПОИСК ПАНЕЛЬ ====================

function toggleSearchPanel() {
    const panel = document.getElementById('searchPanel');
    if (!panel) return;
    const isHidden = panel.style.display === 'none' || panel.style.display === '';
    panel.style.display = isHidden ? 'block' : 'none';

    if (isHidden) {
        const input = panel.querySelector('input[name="q"]');
        if (input) input.focus();
    }
}

// Экспорт в глобальный scope для использования в атрибутах HTML
window.updateSelection = updateSelection;
window.toggleSelectAll = toggleSelectAll;
window.clearSelection = clearSelection;
window.bulkDelete = bulkDelete;
window.bulkDownload = bulkDownload;
window.openRenameModal = openRenameModal;
window.openDeleteModal = openDeleteModal;
window.openMoveModal = openMoveModal;
window.submitMoveCopy = submitMoveCopy;
window.toggleSearchPanel = toggleSearchPanel;

let qpCurrentFileId = null;
let qpCurrentFileType = null;
let qpCurrentFileName = null;
let qpEditMode = false;

async function openQuickPreview(fileId, fileName, fileType) {
    qpCurrentFileId = fileId;
    qpCurrentFileType = fileType;
    qpCurrentFileName = fileName;
    qpEditMode = false;

    const modal = document.getElementById('quickPreviewModal');
    const title = document.getElementById('qpTitle');
    const content = document.getElementById('qpContent');
    const editToggle = document.getElementById('qpEditToggle');
    const saveBtn = document.getElementById('qpSaveBtn');
    if (!modal || !title || !content || !editToggle || !saveBtn) return;

    title.textContent = fileName;
    content.innerHTML = '';
    editToggle.style.display = 'none';
    saveBtn.style.display = 'none';

    // Изображения и PDF — только просмотр (iframe)
    if (fileType === 'image' || (fileType === 'document' && fileName.toLowerCase().endsWith('.pdf'))) {
        const iframe = document.createElement('iframe');
        iframe.src = `/preview_inline/${fileId}`;
        iframe.style.width = '100%';
        iframe.style.height = '70vh';
        iframe.style.border = 'none';
        content.appendChild(iframe);
    } else if (fileType === 'document' || fileType === 'code') {
        // Текст / код — подгружаем содержимое и даём возможность редактировать
        try {
            const resp = await fetch(`/preview_inline/${fileId}`);
            if (!resp.ok) {
                content.textContent = 'Невозможно отобразить предпросмотр';
            } else {
                const text = await resp.text();

                const pre = document.createElement('pre');
                pre.id = 'qpTextView';
                pre.textContent = text;
                pre.style.whiteSpace = 'pre-wrap';
                pre.style.fontSize = '0.8rem';
                pre.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

                const textarea = document.createElement('textarea');
                textarea.id = 'qpTextEdit';
                textarea.value = text;
                textarea.style.display = 'none';
                textarea.style.width = '100%';
                textarea.style.height = '60vh';
                textarea.style.fontSize = '0.8rem';
                textarea.style.fontFamily = pre.style.fontFamily;

                content.appendChild(pre);
                content.appendChild(textarea);

                editToggle.style.display = 'inline-flex';
                saveBtn.style.display = 'none';

                editToggle.onclick = toggleQuickEditMode;
                saveBtn.onclick = saveQuickEdit;
            }
        } catch (e) {
            content.textContent = 'Ошибка загрузки предпросмотра';
        }
    } else {
        content.textContent = 'Предпросмотр для этого типа файла не поддерживается';
    }

    modal.classList.add('active');
}

function toggleQuickEditMode() {
    const pre = document.getElementById('qpTextView');
    const textarea = document.getElementById('qpTextEdit');
    const editToggle = document.getElementById('qpEditToggle');
    const saveBtn = document.getElementById('qpSaveBtn');
    if (!pre || !textarea || !editToggle || !saveBtn) return;

    qpEditMode = !qpEditMode;

    if (qpEditMode) {
        pre.style.display = 'none';
        textarea.style.display = 'block';
        editToggle.textContent = 'Отмена';
        saveBtn.style.display = 'inline-flex';
    } else {
        pre.style.display = 'block';
        textarea.style.display = 'none';
        editToggle.innerHTML = '<i class="fas fa-pen"></i> Редактировать';
        saveBtn.style.display = 'none';
    }
}

async function saveQuickEdit() {
    const textarea = document.getElementById('qpTextEdit');
    if (!textarea || qpCurrentFileId === null) return;

    const editToggle = document.getElementById('qpEditToggle');
    const saveBtn = document.getElementById('qpSaveBtn');
    const status = document.getElementById('qpStatus');

    const formData = new FormData();
    formData.append('content', textarea.value);

    saveBtn.disabled = true;
    if (editToggle) editToggle.disabled = true;
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
        status.style.color = '#10b981';
    }

    try {
        const resp = await fetch(`/edit/${qpCurrentFileId}`, {
            method: 'POST',
            body: formData
        });

        if (!resp.ok) {
            alert('Ошибка сохранения файла');
            if (status) {
                status.style.display = 'inline';
                status.style.color = '#ef4444';
                status.textContent = 'Ошибка сохранения';
            }
        } else {
            const pre = document.getElementById('qpTextView');
            if (pre) pre.textContent = textarea.value;

            // выходим в режим просмотра
            if (qpEditMode) {
                qpEditMode = false;
                toggleQuickEditMode();
            }

            if (status) {
                status.style.display = 'inline';
                status.style.color = '#10b981';
                status.textContent = 'Сохранено';
                setTimeout(() => {
                    status.style.display = 'none';
                }, 1500);
            }
        }
    } catch (e) {
        alert('Ошибка соединения при сохранении файла');
        if (status) {
            status.style.display = 'inline';
            status.style.color = '#ef4444';
            status.textContent = 'Ошибка соединения';
        }
    } finally {
        saveBtn.disabled = false;
        if (editToggle) editToggle.disabled = false;
    }
}

function closeQuickPreview() {
    const modal = document.getElementById('quickPreviewModal');
    const content = document.getElementById('qpContent');
    const editToggle = document.getElementById('qpEditToggle');
    const saveBtn = document.getElementById('qpSaveBtn');
    const status = document.getElementById('qpStatus');
    if (!modal) return;
    modal.classList.remove('active');
    if (content) content.innerHTML = '';
    if (editToggle) {
        editToggle.style.display = 'none';
        editToggle.disabled = false;
        editToggle.innerHTML = '<i class="fas fa-pen"></i> Редактировать';
    }
    if (saveBtn) {
        saveBtn.style.display = 'none';
        saveBtn.disabled = false;
    }
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
    }
    qpCurrentFileId = null;
    qpCurrentFileType = null;
    qpCurrentFileName = null;
    qpEditMode = false;
}
let gqpCurrentFileId = null;
let gqpCurrentGroupId = null;
let gqpCurrentFileType = null;
let gqpCurrentFileName = null;
let gqpEditMode = false;

async function openGroupQuickPreview(fileId, fileName, fileType, groupId) {
    gqpCurrentFileId = fileId;
    gqpCurrentGroupId = groupId;
    gqpCurrentFileType = fileType;
    gqpCurrentFileName = fileName;
    gqpEditMode = false;

    const modal = document.getElementById('groupQuickPreviewModal');
    const title = document.getElementById('gqpTitle');
    const content = document.getElementById('gqpContent');
    const editToggle = document.getElementById('gqpEditToggle');
    const saveBtn = document.getElementById('gqpSaveBtn');
    const status = document.getElementById('gqpStatus');
    if (!modal || !title || !content || !editToggle || !saveBtn) return;

    title.textContent = fileName;
    content.innerHTML = '';
    editToggle.style.display = 'none';
    saveBtn.style.display = 'none';
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
    }

    const baseUrl = `/groups/${groupId}`;

    if (fileType === 'image' || (fileType === 'document' && fileName.toLowerCase().endsWith('.pdf'))) {
        const iframe = document.createElement('iframe');
        iframe.src = `${baseUrl}/preview_inline/${fileId}`;
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.style.display = 'block';
        content.appendChild(iframe);
    } else if (fileType === 'document' || fileType === 'code') {
        try {
            const resp = await fetch(`${baseUrl}/preview_inline/${fileId}`);
            if (!resp.ok) {
                content.textContent = 'Невозможно отобразить предпросмотр';
            } else {
                const text = await resp.text();

                const pre = document.createElement('pre');
                pre.id = 'gqpTextView';
                pre.textContent = text;
                pre.style.whiteSpace = 'pre-wrap';
                pre.style.fontSize = '0.8rem';
                pre.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

                const textarea = document.createElement('textarea');
                textarea.id = 'gqpTextEdit';
                textarea.value = text;
                textarea.style.display = 'none';
                textarea.style.width = '100%';
                textarea.style.minHeight = '300px';
                textarea.style.maxHeight = '60vh';
                textarea.style.fontSize = '0.8rem';
                textarea.style.fontFamily = pre.style.fontFamily;

                content.appendChild(pre);
                content.appendChild(textarea);

                editToggle.style.display = 'inline-flex';
                saveBtn.style.display = 'none';

                editToggle.onclick = toggleGroupQuickEditMode;
                saveBtn.onclick = saveGroupQuickEdit;
            }
        } catch (e) {
            content.textContent = 'Ошибка загрузки предпросмотра';
        }
    } else {
        content.textContent = 'Предпросмотр для этого типа файла не поддерживается';
    }

    modal.classList.add('active');
}

function toggleGroupQuickEditMode() {
    const pre = document.getElementById('gqpTextView');
    const textarea = document.getElementById('gqpTextEdit');
    const editToggle = document.getElementById('gqpEditToggle');
    const saveBtn = document.getElementById('gqpSaveBtn');
    if (!pre || !textarea || !editToggle || !saveBtn) return;

    gqpEditMode = !gqpEditMode;

    if (gqpEditMode) {
        pre.style.display = 'none';
        textarea.style.display = 'block';
        editToggle.textContent = 'Отмена';
        saveBtn.style.display = 'inline-flex';
    } else {
        pre.style.display = 'block';
        textarea.style.display = 'none';
        editToggle.innerHTML = '<i class="fas fa-pen"></i> Редактировать';
        saveBtn.style.display = 'none';
    }
}

async function saveGroupQuickEdit() {
    const textarea = document.getElementById('gqpTextEdit');
    if (!textarea || gqpCurrentFileId === null || gqpCurrentGroupId === null) return;

    const editToggle = document.getElementById('gqpEditToggle');
    const saveBtn = document.getElementById('gqpSaveBtn');
    const status = document.getElementById('gqpStatus');

    const formData = new FormData();
    formData.append('content', textarea.value);

    saveBtn.disabled = true;
    if (editToggle) editToggle.disabled = true;
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
        status.style.color = '#10b981';
    }

    try {
        const resp = await fetch(`/groups/${gqpCurrentGroupId}/edit/${gqpCurrentFileId}`, {
            method: 'POST',
            body: formData
        });

        if (!resp.ok) {
            alert('Ошибка сохранения файла');
            if (status) {
                status.style.display = 'inline';
                status.style.color = '#ef4444';
                status.textContent = 'Ошибка сохранения';
            }
        } else {
            const pre = document.getElementById('gqpTextView');
            if (pre) pre.textContent = textarea.value;

            if (gqpEditMode) {
                gqpEditMode = false;
                toggleGroupQuickEditMode();
            }

            if (status) {
                status.style.display = 'inline';
                status.style.color = '#10b981';
                status.textContent = 'Сохранено';
                setTimeout(() => {
                    status.style.display = 'none';
                }, 1500);
            }
        }
    } catch (e) {
        alert('Ошибка соединения при сохранении файла');
        if (status) {
            status.style.display = 'inline';
            status.style.color = '#ef4444';
            status.textContent = 'Ошибка соединения';
        }
    } finally {
        saveBtn.disabled = false;
        if (editToggle) editToggle.disabled = false;
    }
}

function closeGroupQuickPreview() {
    const modal = document.getElementById('groupQuickPreviewModal');
    const content = document.getElementById('gqpContent');
    const editToggle = document.getElementById('gqpEditToggle');
    const saveBtn = document.getElementById('gqpSaveBtn');
    const status = document.getElementById('gqpStatus');
    if (!modal) return;
    modal.classList.remove('active');
    if (content) content.innerHTML = '';
    if (editToggle) {
        editToggle.style.display = 'none';
        editToggle.disabled = false;
        editToggle.innerHTML = '<i class="fas fa-pen"></i> Редактировать';
    }
    if (saveBtn) {
        saveBtn.style.display = 'none';
        saveBtn.disabled = false;
    }
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
    }
    gqpCurrentFileId = null;
    gqpCurrentGroupId = null;
    gqpCurrentFileType = null;
    gqpCurrentFileName = null;
    gqpEditMode = false;
}

window.openGroupQuickPreview = openGroupQuickPreview;
window.closeGroupQuickPreview = closeGroupQuickPreview;


window.openQuickPreview = openQuickPreview;
window.closeQuickPreview = closeQuickPreview;
