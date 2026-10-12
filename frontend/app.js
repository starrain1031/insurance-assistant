document.addEventListener('DOMContentLoaded', function () {
    const chatContainer = document.getElementById('chatContainer');
    const userInput = document.getElementById('userInput');
    const sendButton = document.getElementById('sendButton');
    const cancelButton = document.getElementById('cancelButton');
    const newChatButton = document.getElementById('newChatButton');
    const serviceStatus = document.getElementById('serviceStatus');
    const serviceStatusText = document.getElementById('serviceStatusText');
    const suggestionChips = document.querySelectorAll('.suggestion-chip');
    const welcomeMarkup = chatContainer.innerHTML;

    // 默认同源；分开部署时可在 HTML 的 api-base-url 元标签中指定地址。
    const configuredApiBase = document.querySelector('meta[name="api-base-url"]')?.content.trim();
    const API_BASE_URL = (configuredApiBase || (
        window.location.protocol === 'file:' ? 'http://localhost:8000' : window.location.origin
    )).replace(/\/+$/, '');
    const REQUEST_TIMEOUT_MS = 120_000;
    const STREAM_IDLE_TIMEOUT_MS = 30_000;
    const HEALTH_TIMEOUT_MS = 5_000;
    const HEALTH_INTERVAL_MS = 30_000;
    const THREAD_STORAGE_KEY = 'insurance_chat_thread_id';
    let activeRequest = null;
    let healthController = null;
    let healthInterval = null;

    function createThreadId() {
        if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
        return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
    }

    function saveThreadId(id) {
        try {
            sessionStorage.setItem(THREAD_STORAGE_KEY, id);
        } catch (error) {
            console.warn('无法保存会话，刷新后将开始新对话。', error);
        }
    }

    let currentThreadId;
    try {
        currentThreadId = sessionStorage.getItem(THREAD_STORAGE_KEY);
    } catch (error) {
        console.warn('无法读取会话，将创建新会话。', error);
    }
    currentThreadId = typeof currentThreadId === 'string' ? currentThreadId.trim() : '';
    if (!currentThreadId || currentThreadId === 'default') currentThreadId = createThreadId();
    saveThreadId(currentThreadId);

    function setServiceStatus(state, text, detail) {
        serviceStatus.dataset.state = state;
        serviceStatusText.textContent = text;
        serviceStatus.title = detail + ' 点击重新检测。';
    }

    async function checkService() {
        if (healthController) healthController.abort();
        const controller = new AbortController();
        healthController = controller;
        if (!navigator.onLine) {
            healthController = null;
            setServiceStatus('offline', '网络已断开', '浏览器报告当前没有网络连接。');
            return;
        }
        setServiceStatus('checking', '检测中…', '正在检测服务连接。');
        const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
        try {
            const response = await fetch(`${API_BASE_URL}/health`, {
                signal: controller.signal,
                cache: 'no-store',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (data.status !== 'alive') throw new Error('Unexpected health response');
            if (healthController === controller) {
                setServiceStatus('reachable', '服务可连接',
                    `最近检测：${new Date().toLocaleTimeString()}。服务可连接，回答是否成功以实际结果为准。`);
            }
        } catch (error) {
            if (healthController === controller) {
                setServiceStatus('unreachable', '连接失败',
                    '未能连接服务，请检查网络或稍后重新检测。');
            }
        } finally {
            clearTimeout(timer);
            if (healthController === controller) healthController = null;
        }
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function nearBottom() {
        return chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < 100;
    }

    function escapeMarkdownHtml(value) {
        return String(value).replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[char]);
    }

    // 原始 HTML 作为文字展示；Markdown 生成的 HTML 再经过安全过滤。
    const markdownParser = window.marked ? new window.marked.Marked({
        gfm: true,
        breaks: true,
        async: false,
        renderer: {
            html({ text }) { return escapeMarkdownHtml(text); },
            // 图片提供链接，不在回复中自动请求第三方图片。
            image({ href, text }) {
                return `<a href="${escapeMarkdownHtml(href)}">${escapeMarkdownHtml(text || '查看图片')}</a>`;
            },
        },
    }) : null;

    function renderMarkdown(target, source) {
        if (!markdownParser || !window.DOMPurify?.isSupported) {
            target.classList.remove('markdown-body');
            target.textContent = source;
            return;
        }
        try {
            const fragment = window.DOMPurify.sanitize(markdownParser.parse(source), {
                RETURN_DOM_FRAGMENT: true,
                ALLOWED_TAGS: [
                    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'strong', 'em', 'del', 's', 'blockquote', 'ol', 'ul', 'li',
                    'pre', 'code', 'table', 'thead', 'tbody', 'tfoot', 'tr',
                    'th', 'td', 'hr', 'a', 'input',
                ],
                ALLOWED_ATTR: ['href', 'title', 'class', 'align', 'start', 'type', 'checked', 'disabled'],
                ALLOW_DATA_ATTR: false,
                ALLOW_ARIA_ATTR: false,
            });
            fragment.querySelectorAll('a').forEach(link => {
                const href = link.getAttribute('href');
                if (!href) return;
                try {
                    const url = new URL(href, window.location.href);
                    if (!['https:', 'http:', 'mailto:'].includes(url.protocol)) {
                        link.removeAttribute('href');
                        return;
                    }
                    link.setAttribute('target', '_blank');
                    link.setAttribute('rel', 'noopener noreferrer');
                } catch {
                    link.removeAttribute('href');
                }
            });
            fragment.querySelectorAll('input').forEach(input => {
                input.type = 'checkbox';
                input.disabled = true;
            });
            fragment.querySelectorAll('table').forEach(table => {
                const wrapper = document.createElement('div');
                wrapper.className = 'markdown-table';
                wrapper.tabIndex = 0;
                wrapper.setAttribute('role', 'region');
                wrapper.setAttribute('aria-label', '回答中的表格，可横向滚动');
                table.replaceWith(wrapper);
                wrapper.appendChild(table);
            });
            target.classList.add('markdown-body');
            target.replaceChildren(fragment);
        } catch (error) {
            // 渲染失败时仍显示原文，不影响流式接收及错误提示。
            console.warn('Markdown 渲染失败，已使用纯文本。', error);
            target.classList.remove('markdown-body');
            target.textContent = source;
        }
    }

    function addMessage(role, text) {
        const element = document.createElement('div');
        element.className = `message ${role}-message`;
        const header = document.createElement('div');
        header.className = 'message-header';
        // 固定的界面标记使用 innerHTML；用户消息按纯文本显示，AI 回复经过 Markdown 解析和过滤。
        header.innerHTML = role === 'user'
            ? '<span>您</span><div class="user-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg></div>'
            : '<div class="bot-avatar"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 4 6v6c0 4.5 8 9 8 9s8-4.5 8-9V6Z"/><path d="m8.5 12 2.3 2.3 4.7-4.6"/></svg></div><span>安心宝</span>';
        const content = document.createElement('div');
        content.className = 'message-content';
        content.textContent = text;
        element.append(header, content);
        chatContainer.appendChild(element);
        scrollToBottom();
        return { element, content };
    }

    function addNotice(message, text, kind) {
        const stickToBottom = nearBottom();
        const notice = document.createElement('div');
        notice.className = `message-notice ${kind}`;
        notice.setAttribute('role', 'status');
        notice.textContent = text;
        message.element.appendChild(notice);
        if (stickToBottom) scrollToBottom();
    }

    function setBusy(busy) {
        userInput.disabled = busy;
        sendButton.disabled = busy;
        newChatButton.disabled = busy;
        cancelButton.hidden = !busy;
        cancelButton.disabled = false;
        cancelButton.textContent = '取消';
        chatContainer.setAttribute('aria-busy', String(busy));
        suggestionChips.forEach(chip => { chip.disabled = busy; });
    }

    function resizeInput() {
        userInput.style.height = 'auto';
        userInput.style.height = `${Math.min(userInput.scrollHeight, 160)}px`;
    }

    class ChatError extends Error {
        constructor(kind, message, status = null) {
            super(message);
            this.kind = kind;
            this.status = status;
        }
    }

    function describeError(error, request) {
        if (request.stopReason === 'cancel') {
            return '已取消接收。服务端可能仍在处理本次问题；已收到的回答可能不完整。';
        }
        if (request.stopReason === 'timeout') {
            return '等待已超过 120 秒，已停止接收。服务端可能仍在处理，请稍后再试。';
        }
        if (request.stopReason === 'idle') {
            return '连续 30 秒没有收到服务数据，连接可能中断，已停止接收。已收到的内容已保留。';
        }
        if (!navigator.onLine) return '网络已断开，请恢复网络后再发送。';
        if (error.kind === 'http') {
            const status = error.status;
            if (status === 400 || status === 422) return '请求内容不符合要求，请检查问题内容后重新发送。';
            if (status === 401 || status === 403) return '当前请求未获授权，请联系服务管理员确认访问权限。';
            if (status === 404) return '未找到聊天服务，请检查服务地址是否正确。';
            if (status === 408 || status === 504) return '服务响应超时，请稍后再试。';
            if (status === 429) return '请求过于频繁或服务额度不足，请稍后再试。';
            if (status >= 500) return `服务暂时无法完成回答（HTTP ${status}），请稍后再试。`;
            return `请求未成功（HTTP ${status}），请稍后再试。`;
        }
        if (error.kind === 'protocol') return '收到的回答格式异常，请稍后再试；已收到的内容已保留。';
        if (error.kind === 'incomplete') return '连接提前结束，回答可能不完整；已收到的内容已保留。';
        if (error.kind === 'empty') return '服务没有返回回答，请换一种问法或稍后再试。';
        if (error.kind === 'server') return '服务在回答过程中报告错误，请稍后再试；已收到的内容已保留。';
        return '连接失败或传输中断，请检查网络和服务地址，也可能是浏览器跨域限制。';
    }

    function stopRequest(reason) {
        if (!activeRequest || activeRequest.controller.signal.aborted) return;
        activeRequest.stopReason = reason;
        activeRequest.controller.abort();
    }

    async function sendMessage(rawMessage) {
        const message = rawMessage.trim();
        if (activeRequest || !message) return;
        const request = {
            controller: new AbortController(),
            stopReason: null,
            threadId: currentThreadId,
        };
        activeRequest = request;
        setBusy(true);
        userInput.value = '';
        resizeInput();
        chatContainer.querySelector('.welcome-message')?.remove();
        addMessage('user', message);
        const bot = addMessage('bot', '');
        const indicator = document.createElement('div');
        indicator.className = 'typing-indicator';
        indicator.textContent = '正在准备回答…';
        bot.element.appendChild(indicator);
        scrollToBottom();

        let reader = null;
        let answer = '';
        let completed = false;
        let idleTimer = null;
        let renderTimer = null;
        const timeout = setTimeout(() => stopRequest('timeout'), REQUEST_TIMEOUT_MS);
        function flushAnswer() {
            clearTimeout(renderTimer);
            renderTimer = null;
            if (!answer) return;
            const stickToBottom = nearBottom();
            renderMarkdown(bot.content, answer);
            if (stickToBottom) scrollToBottom();
        }
        function scheduleAnswer() {
            // 首片段立即展示，后续合并高频 token，减少 Markdown 全文重绘。
            if (!bot.content.textContent) {
                flushAnswer();
            } else if (renderTimer === null) {
                renderTimer = setTimeout(flushAnswer, 40);
            }
        }
        function refreshIdleTimer() {
            clearTimeout(idleTimer);
            idleTimer = setTimeout(() => stopRequest('idle'), STREAM_IDLE_TIMEOUT_MS);
        }
        function processEvent(frame) {
            const data = frame.split(/\r?\n/)
                .filter(line => line.startsWith('data:'))
                .map(line => line.slice(5).replace(/^ /, ''))
                .join('\n');
            if (!data) return; // SSE 注释或心跳。
            if (data.trim() === '[DONE]') { completed = true; return; }
            let parsed;
            try {
                parsed = JSON.parse(data);
            } catch {
                throw new ChatError('protocol', 'Invalid event JSON');
            }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                throw new ChatError('protocol', 'Invalid event payload');
            }
            if ('thread_id' in parsed) {
                if (typeof parsed.thread_id !== 'string' || !parsed.thread_id.trim()
                    || parsed.thread_id !== request.threadId) {
                    throw new ChatError('protocol', 'Unexpected conversation ID');
                }
                currentThreadId = parsed.thread_id;
                saveThreadId(currentThreadId);
                if (!answer) indicator.textContent = '正在检索资料或生成回答…';
            }
            if (parsed.error) throw new ChatError('server', 'Server reported an error');
            if ('content' in parsed && typeof parsed.content !== 'string') {
                throw new ChatError('protocol', 'Invalid content type');
            }
            if (parsed.content) {
                answer += parsed.content;
                scheduleAnswer();
                indicator.remove();
            }
        }

        try {
            if (!navigator.onLine) throw new ChatError('network', 'Offline');
            const response = await fetch(`${API_BASE_URL}/chat/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, thread_id: request.threadId }),
                signal: request.controller.signal,
            });
            if (!response.ok) throw new ChatError('http', 'Request rejected', response.status);
            if (!response.body || !response.headers.get('content-type')?.toLowerCase().includes('text/event-stream')) {
                throw new ChatError('protocol', 'Expected an event stream');
            }
            reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            refreshIdleTimer();
            while (!completed) {
                const { done, value } = await reader.read();
                if (request.controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
                if (!done) refreshIdleTimer();
                buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
                let boundary;
                while (!completed && (boundary = /\r?\n\r?\n/.exec(buffer))) {
                    const frame = buffer.slice(0, boundary.index);
                    buffer = buffer.slice(boundary.index + boundary[0].length);
                    processEvent(frame);
                }
                if (done) {
                    // 接受最后一帧没有额外空行的响应，但仍要求 DONE 标记。
                    if (!completed && buffer.trim()) processEvent(buffer);
                    break;
                }
            }
            if (!completed) throw new ChatError('incomplete', 'Missing completion marker');
            if (!answer.trim()) throw new ChatError('empty', 'Empty answer');
        } catch (error) {
            addNotice(bot, describeError(error, request), request.stopReason === 'cancel' ? 'notice-info' : 'notice-error');
            // 不自动重发，避免服务器仍在处理时重复提交同一问题。
            if (!answer) { userInput.value = message; resizeInput(); }
            if (request.stopReason !== 'cancel') void checkService();
        } finally {
            clearTimeout(timeout);
            clearTimeout(idleTimer);
            flushAnswer();
            indicator.remove();
            if (reader) {
                void reader.cancel().catch(() => {});
                reader.releaseLock();
            }
            request.controller.abort();
            if (activeRequest === request) {
                activeRequest = null;
                setBusy(false);
                userInput.focus();
            }
        }
    }

    sendButton.addEventListener('click', () => { void sendMessage(userInput.value); });
    userInput.addEventListener('input', resizeInput);
    window.addEventListener('resize', resizeInput);
    userInput.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            void sendMessage(userInput.value);
        }
    });
    cancelButton.addEventListener('click', () => {
        cancelButton.disabled = true;
        cancelButton.textContent = '正在取消…';
        stopRequest('cancel');
    });
    suggestionChips.forEach(chip => {
        chip.addEventListener('click', () => { void sendMessage(chip.dataset.question); });
    });
    newChatButton.addEventListener('click', () => {
        if (activeRequest) return;
        currentThreadId = createThreadId();
        saveThreadId(currentThreadId);
        chatContainer.innerHTML = welcomeMarkup;
        userInput.value = '';
        resizeInput();
        userInput.focus();
    });
    serviceStatus.addEventListener('click', () => { void checkService(); });
    window.addEventListener('online', () => { void checkService(); });
    window.addEventListener('offline', () => { void checkService(); });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) void checkService();
    });
    function startHealthChecks() {
        clearInterval(healthInterval);
        void checkService();
        healthInterval = setInterval(() => {
            if (!document.hidden) void checkService();
        }, HEALTH_INTERVAL_MS);
    }
    window.addEventListener('pagehide', () => {
        clearInterval(healthInterval);
        if (healthController) { const controller = healthController; healthController = null; controller.abort(); }
        stopRequest('cancel');
    });
    window.addEventListener('pageshow', event => {
        if (event.persisted) startHealthChecks();
    });
    startHealthChecks();
    resizeInput();
    userInput.focus();
});
