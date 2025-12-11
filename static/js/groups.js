console.log('groups.js loaded');

// ===== Приглашения, QR и пин =====

document.addEventListener('DOMContentLoaded', () => {
    const genBtn = document.getElementById('gen-btn');
    if (genBtn) {
        genBtn.addEventListener('click', async function () {
            const btn = this;
            btn.disabled = true;

            const pinInput = document.getElementById('pin-input');
            const noPinCheckbox = document.getElementById('no-pin');

            const fd = new FormData();
            if (noPinCheckbox && noPinCheckbox.checked) {
                fd.append('no_pin', '1');
            } else if (pinInput && pinInput.value.trim()) {
                fd.append('pincode', pinInput.value.trim());
            }

            const inviteUrl = genBtn.dataset.inviteUrl;

            try {
                const res = await fetch(inviteUrl, {
                    method: 'POST',
                    body: fd
                });

                const data = await res.json();

                if (!res.ok || !data.success) {
                    alert(data.error || ('Ошибка, статус ' + res.status));
                    return;
                }

                const inviteBox = document.getElementById('invite-box');
                const invLink = document.getElementById('inv-link');
                if (inviteBox && invLink) {
                    inviteBox.style.display = 'block';
                    invLink.value = data.invite_link;
                }

                const qrBtn = document.getElementById('qr-btn');
                if (qrBtn) qrBtn.style.display = 'inline-flex';

                const pinBox = document.getElementById('pin-box');
                const pinText = document.getElementById('pin-text');
                if (data.pincode && pinBox && pinText) {
                    pinBox.style.display = 'block';
                    pinText.textContent = data.pincode;
                } else if (pinBox) {
                    pinBox.style.display = 'none';
                }

                btn.innerHTML = 'Создать ещё';
            } catch (e) {
                console.error(e);
                alert('Ошибка сети или JS');
            } finally {
                btn.disabled = false;
            }
        });
    }

    // Drag&Drop в модалке загрузки группы
    const gUploadArea = document.getElementById('groupUploadArea');
    const gFileInput  = document.getElementById('groupFileInput');
    const gFileList   = document.getElementById('groupFileList');

    if (gUploadArea && gFileInput) {
        gUploadArea.addEventListener('dragover', e => {
            e.preventDefault();
            gUploadArea.classList.add('dragover');
        });
        gUploadArea.addEventListener('dragleave', () => {
            gUploadArea.classList.remove('dragover');
        });
        gUploadArea.addEventListener('drop', e => {
            e.preventDefault();
            gUploadArea.classList.remove('dragover');
            gFileInput.files = e.dataTransfer.files;
            updateGroupFileList();
        });
        gFileInput.addEventListener('change', updateGroupFileList);
    }

    function updateGroupFileList() {
        if (!gFileList || !gFileInput) return;
        gFileList.innerHTML = '';
        for (let f of gFileInput.files) {
            const item = document.createElement('div');
            item.className = 'file-list-item';
            item.innerHTML = `<i class="fas fa-file"></i><span>${f.name}</span>`;
            gFileList.appendChild(item);
        }
    }
});

// QR-код
function showQRCode(url) {
    const qrcodeBox = document.getElementById('qrcode');
    const modal = document.getElementById('qrModal');
    if (!qrcodeBox || !modal) return;
    qrcodeBox.innerHTML = '';
    if (url && url.startsWith('/')) url = window.location.origin + url;
    if (window.QRCode && url) {
        new QRCode(qrcodeBox, { text: url, width: 200, height: 200 });
    }
    modal.classList.add('active');
}

// Копирование (если не используешь общий из main.js)
function copyToClipboard(sel) {
    const el = document.querySelector(sel);
    if (!el) return;
    el.select();
    document.execCommand('copy');
    alert('Скопировано');
}

function copyText(txt) {
    const t = document.createElement('input');
    t.value = txt;
    document.body.appendChild(t);
    t.select();
    document.execCommand('copy');
    document.body.removeChild(t);
    alert('Скопировано');
}

// Переименование / удаление одного файла
function openGroupRenameModal(groupId, fileId, fileName) {
    const form = document.getElementById('renameForm');
    const input = document.getElementById('new_name');
    const modal = document.getElementById('renameModal');
    if (!form || !input || !modal) return;
    form.action = `/groups/${groupId}/rename/${fileId}`;
    input.value = fileName;
    modal.classList.add('active');
}

function openGroupDeleteModal(fileId) {
    const idsInput = document.getElementById('group_delete_ids');
    const actionInput = document.getElementById('group_delete_action');
    const modal = document.getElementById('groupDeleteModal');
    if (!idsInput || !actionInput || !modal) return;
    idsInput.value = fileId;
    actionInput.value = 'trash';
    modal.classList.add('active');
}

function submitGroupDelete(action) {
    const actionInput = document.getElementById('group_delete_action');
    const form = document.getElementById('groupDeleteForm');
    if (!actionInput || !form) return;
    actionInput.value = action;
    form.submit();
}

// Массовые действия (используют getSelectedIds из files.js)
function bulkGroupDelete(type) {
    const ids = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!ids.length) {
        alert('Выберите файлы для удаления');
        return;
    }
    const actionText = type === 'permanent' ? 'удалить навсегда' : 'переместить в корзину';
    if (!confirm(`Вы уверены, что хотите ${actionText} ${ids.length} файл(ов)?`)) return;

    const form = document.getElementById('groupDeleteForm');
    if (!form) return;

    form.querySelectorAll('input[name="file_ids"]').forEach(el => el.remove());

    ids.forEach(id => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'file_ids';
        input.value = id;
        form.appendChild(input);
    });

    const actionInput = document.getElementById('group_delete_action');
    if (actionInput) {
        actionInput.value = type === 'permanent' ? 'delete_permanent' : 'trash';
    }

    form.submit();
}

function bulkGroupDownload() {
    const ids = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!ids.length) {
        alert('Выберите файлы для скачивания');
        return;
    }

    const holder = document.getElementById('groupActions');
    const downloadUrl = holder ? holder.dataset.downloadUrl : null;
    if (!downloadUrl) return;

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = downloadUrl;

    ids.forEach(id => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'file_ids';
        input.value = id;
        form.appendChild(input);
    });

    document.body.appendChild(form);
    form.submit();
}

// Move / Copy
function openGroupMoveModal() {
    const ids = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!ids.length) return alert('Выберите файлы');

    const modal = document.getElementById('groupMoveModal');
    if (!modal) return;

    modal.classList.add('active');
    loadGroupFolders();
}

async function loadGroupFolders() {
    const list = document.getElementById('groupFolderList');
    if (!list) return;

    const url = list.dataset.treeUrl;
    if (!url) return;

    try {
        const response = await fetch(url);
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
                <input type="radio" name="group_target_folder" value="${f.id}">
                <span class="folder-icon"><i class="fas fa-folder"></i></span>
                <span class="folder-name" style="margin-left: ${f.parent_id ? '20px' : '0'}">${f.name}</span>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        list.innerHTML = '<p style="color: red;">Ошибка загрузки</p>';
    }
}

function submitGroupMoveCopy(action) {
    const selected = document.querySelector('input[name="group_target_folder"]:checked');
    if (!selected) return alert('Выберите папку назначения');

    const targetId = selected.value === 'root' ? 'root' : selected.value;
    const fileIds = window.getSelectedIds ? window.getSelectedIds() : [];
    if (!fileIds.length) return alert('Не выбраны файлы');

    const actionInput = document.getElementById('group_mc_action');
    const targetInput = document.getElementById('group_mc_target_id');
    const container = document.getElementById('group_mc_files_container');
    const form = document.getElementById('groupMoveCopyForm');
    if (!actionInput || !targetInput || !container || !form) return;

    actionInput.value = action;
    targetInput.value = targetId;

    container.innerHTML = fileIds
        .map(id => `<input type="hidden" name="file_ids" value="${id}">`)
        .join('');

    form.submit();
}

// Поиск-панель (если не используешь общую)
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

// Экспорт в глобал
window.showQRCode = showQRCode;
window.copyToClipboard = copyToClipboard;
window.copyText = copyText;
window.openGroupRenameModal = openGroupRenameModal;
window.openGroupDeleteModal = openGroupDeleteModal;
window.submitGroupDelete = submitGroupDelete;
window.bulkGroupDelete = bulkGroupDelete;
window.bulkGroupDownload = bulkGroupDownload;
window.openGroupMoveModal = openGroupMoveModal;
window.submitGroupMoveCopy = submitGroupMoveCopy;
window.toggleSearchPanel = toggleSearchPanel;
