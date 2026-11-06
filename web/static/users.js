const message = document.getElementById('message');
const usersContainer = document.getElementById('users');
const csrfToken = document.getElementsByName("csrf-token")[0].content


function showQrCode(qrData) {
    const qrContainer = document.getElementById('qrcode');

    // Удаляем предыдущий QR-код
    qrContainer.innerHTML = '';
    
    new QRCode(qrContainer, qrData)
    document.getElementById('qr-modal').classList.remove('hidden');
}

// Вызывается через кнопку внутри qr-modal
function closeQrModal() {
    document.getElementById('qr-modal').classList.add('hidden');
}

// Отображение сообщений
function showMessage(text, type = 'error', key = null) {
    message.className = `message ${type}`;
    message.replaceChildren();

    message.appendChild(document.createTextNode(text));

    if (key) {
        const pre = document.createElement('pre');
        pre.textContent = key;
        message.appendChild(pre);
    }
}

// Скрытие сообщений
function clearMessage() {
    message.className = 'message';
    message.replaceChildren();
}


// Обработка ответов сервера
async function apiRequest(url, options = {}, returnResponseObj = false) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            "X-CSRF-Token": csrfToken,
            ...options.headers
        }
    });

    if (returnResponseObj) return response

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || 'Ошибка сервера');
    }

    return data;
}

// Показать / скрыть форму создания
// Вызывается в html файле через onClick
function toggleCreateForm() {
    document.getElementById('createForm')
        .classList.toggle('active');
}

async function logout() {
    const response = await apiRequest("/logout", {method: "POST"}, true)

    if (response.ok) {
        window.location.href = response.url
    } else {
        showMessage(`Ошибка запроса: ${response.statusText}`)
    }
}


// Создание пользователя
document.getElementById('createForm').addEventListener(
    'submit',
    async function(event) {
        event.preventDefault();
        clearMessage();

        const nameInput = document.getElementById('userName');
        const name = nameInput.value.trim();

        if (!name) return;

        try {
            const data = await apiRequest('/api/users', {
                method: 'POST',
                body: JSON.stringify({ name })
            });

            addUser(data.user);

            this.reset();
            this.classList.remove('active');

            showMessage(
                'Пользователь создан. Сохраните ключ — повторно получить его будет невозможно.',
                'success',
                data.key
            );

            const qrData = `${data.user.user_id} ${data.key}`;
            showQrCode(qrData);

        } catch (error) {
            showMessage(error.message);
            console.error(error)
        }
    }
);

// Добавление пользователя в интерфейс
function addUser(user) {
    document.getElementById('empty')?.remove();

    const element = document.createElement('div');
    element.className = 'user';
    element.dataset.userId = user.user_id;

    const info = document.createElement('div');
    info.className = 'user-info';

    const name = document.createElement('div');
    name.className = 'user-name';
    name.textContent = user.name;

    const id = document.createElement('div');
    id.className = 'user-id';
    id.textContent = `ID: ${user.user_id}`;

    info.append(name, id);

    const actions = document.createElement('div');
    actions.className = 'user-actions';

    const regenerate = document.createElement('button');
    regenerate.type = 'button';
    regenerate.textContent = 'Новый ключ';
    regenerate.addEventListener('click', function() {
        regenerateKey(user.user_id, this);
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'delete-btn';
    remove.textContent = 'Удалить';
    remove.addEventListener('click', function() {
        deleteUser(user.user_id, this);
    });

    actions.append(regenerate, remove);
    element.append(info, actions);

    usersContainer.appendChild(element);
}

// Перегенерация ключа
async function regenerateKey(userId, button) {
    if (!confirm('Перегенерировать ключ? Старый ключ перестанет работать.')) {
        return;
    }

    clearMessage();
    button.disabled = true;

    try {
        const data = await apiRequest(
            `/api/users/${encodeURIComponent(userId)}/regenerate-key`,
            { method: 'POST' }
        );

        showMessage(
            'Новый ключ создан. Сохраните его сейчас — повторно получить его будет невозможно.',
            'success',
            data.key
        );

        const qrData = `${userId} ${data.key}`
        showQrCode(qrData)
    } catch (error) {
        showMessage(error.message);
        console.error(error)
    } finally {
        button.disabled = false;
    }
}

// Удаление пользователя
async function deleteUser(userId, button) {
    if (!confirm('Удалить пользователя? Это действие необратимо.')) {
        return;
    }

    clearMessage();
    button.disabled = true;

    try {
        await apiRequest(
            `/api/users/${encodeURIComponent(userId)}`,
            { method: 'DELETE' }
        );

        document.querySelector(
            `[data-user-id="${CSS.escape(userId)}"]`
        )?.remove();

        if (!usersContainer.querySelector('.user')) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.id = 'empty';
            empty.textContent = 'Пользователей пока нет';
            usersContainer.appendChild(empty);
        }

        showMessage('Пользователь удалён.', 'success');

    } catch (error) {
        showMessage(error.message);
        button.disabled = false;
    }
}
