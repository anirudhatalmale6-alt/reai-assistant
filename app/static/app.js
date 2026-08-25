// ===== State =====
let conversationId = null;
let isStreaming = false;

// ===== DOM References =====
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');
const sidebarList = document.getElementById('sidebar-list');
const menuBtn = document.getElementById('menu-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const chatContainer = document.getElementById('chat-container');
const welcomeScreen = document.getElementById('welcome-screen');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const connectBtn = document.getElementById('connect-btn');
const metaConnectBtn = document.getElementById('meta-connect-btn');
const statUnread = document.getElementById('stat-unread');
const statToday = document.getElementById('stat-today');
const statTomorrow = document.getElementById('stat-tomorrow');

// Google auth modal
const googleAuthModal = document.getElementById('google-auth-modal');
const googleStep1 = document.getElementById('google-step-1');
const googleStep2 = document.getElementById('google-step-2');
const googleAuthorizeBtn = document.getElementById('google-authorize-btn');
const googleAuthCode = document.getElementById('google-auth-code');
const googleSubmitBtn = document.getElementById('google-submit-btn');
const googleModalClose = document.getElementById('google-modal-close');

// Meta auth modal
const metaAuthModal = document.getElementById('meta-auth-modal');
const metaStep1 = document.getElementById('meta-step-1');
const metaStep2 = document.getElementById('meta-step-2');
const metaAuthorizeBtn = document.getElementById('meta-authorize-btn');
const metaAuthCode = document.getElementById('meta-auth-code');
const metaSubmitBtn = document.getElementById('meta-submit-btn');
const metaModalClose = document.getElementById('meta-modal-close');

// Lofty auth modal
const loftyConnectBtn = document.getElementById('lofty-connect-btn');
const loftyAuthModal = document.getElementById('lofty-auth-modal');
const loftyAuthCode = document.getElementById('lofty-auth-code');
const loftySubmitBtn = document.getElementById('lofty-submit-btn');
const loftyModalClose = document.getElementById('lofty-modal-close');
const loftyAuthError = document.getElementById('lofty-auth-error');

// ===== Tool Names Mapping =====
const toolNames = {
    search_emails: 'Searching emails',
    read_email: 'Reading email',
    send_email: 'Sending email',
    list_calendar_events: 'Listing calendar events',
    create_calendar_event: 'Creating calendar event',
    find_free_slots: 'Finding free time slots',
    search_drive_files: 'Searching Drive files',
    read_drive_file: 'Reading Drive file',
    get_crm_leads: 'Getting CRM leads',
    get_crm_lead_details: 'Getting lead details',
    search_crm_leads: 'Searching CRM leads',
    get_lead_activities: 'Getting lead activities',
    update_crm_lead: 'Updating CRM lead',
    add_lead_note: 'Adding lead note',
    get_pipeline_summary: 'Getting pipeline summary',
    search_listings: 'Searching MLS listings',
    generate_cma: 'Generating CMA report',
    get_listing_details: 'Getting listing details',
    generate_daily_brief: 'Generating daily brief',
    post_to_facebook: 'Posting to Facebook',
    post_to_instagram: 'Posting to Instagram',
    get_facebook_posts: 'Getting Facebook posts',
    get_facebook_messages: 'Getting Facebook messages',
    read_facebook_conversation: 'Reading Facebook conversation',
    reply_facebook_message: 'Replying on Facebook',
    get_instagram_dms: 'Getting Instagram DMs',
    reply_instagram_dm: 'Replying on Instagram'
};

// ===== Utility =====
function isMobile() {
    return window.innerWidth <= 768;
}

// ===== Sidebar Toggle =====
function toggleSidebar() {
    if (isMobile()) {
        sidebar.classList.toggle('visible');
        sidebarOverlay.classList.toggle('visible');
    }
}

function closeSidebar() {
    if (isMobile()) {
        sidebar.classList.remove('visible');
        sidebarOverlay.classList.remove('visible');
    }
}

menuBtn.addEventListener('click', toggleSidebar);
sidebarOverlay.addEventListener('click', closeSidebar);

// ===== New Chat =====
newChatBtn.addEventListener('click', function () {
    conversationId = null;
    chatContainer.innerHTML = '';
    chatContainer.appendChild(welcomeScreen);
    welcomeScreen.style.display = '';
    document.querySelectorAll('.sidebar-item').forEach(function (el) {
        el.classList.remove('active');
    });
    closeSidebar();
});

// ===== Load Conversations =====
// The list is grouped by day and searchable. A flat run of 37 rows, six of them
// reading "Create a social media post", is technically the whole history and
// practically unusable - you can see it but you can't find anything in it.

var searchTerm = '';

// Local midnight, not UTC. created_at comes back as ...+00:00, so a chat at
// 9pm Toronto is already "tomorrow" in UTC and would land in the wrong bucket.
function startOfDay(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function dayBucket(iso) {
    var t = new Date(iso);
    if (isNaN(t)) { return { key: 'zz', label: 'Earlier', stamp: '' }; }
    var days = Math.round((startOfDay(new Date()) - startOfDay(t)) / 86400000);
    var time = t.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (days <= 0) { return { key: 'a', label: 'Today', stamp: time }; }
    if (days === 1) { return { key: 'b', label: 'Yesterday', stamp: 'Yesterday' }; }
    if (days < 7) {
        return { key: 'c', label: 'Previous 7 days',
                 stamp: t.toLocaleDateString([], { weekday: 'long' }) };
    }
    if (days < 30) {
        return { key: 'd', label: 'Previous 30 days',
                 stamp: t.toLocaleDateString([], { month: 'short', day: 'numeric' }) };
    }
    return { key: 'e', label: 'Older',
             stamp: t.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) };
}

// Titles are cut from the opening message, so a multi-line social post becomes
// a title with newlines in it. Flatten before it goes in the sidebar.
function oneLine(s) {
    return (s || '').replace(/\s+/g, ' ').trim();
}

function highlight(text, term) {
    var safe = escapeHtml(text);
    if (!term) { return safe; }
    var i = safe.toLowerCase().indexOf(escapeHtml(term).toLowerCase());
    if (i < 0) { return safe; }
    var n = escapeHtml(term).length;
    return safe.slice(0, i) + '<mark>' + safe.slice(i, i + n) + '</mark>' + safe.slice(i + n);
}

function loadConversations() {
    var url = '/api/conversations' + (searchTerm ? '?q=' + encodeURIComponent(searchTerm) : '');
    var term = searchTerm;
    fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // A slow response for an old search term must not overwrite the
            // results for what he's typing now.
            if (term !== searchTerm) { return; }

            sidebarList.innerHTML = '';
            var convos = data.conversations || [];

            if (!convos.length) {
                var empty = document.createElement('div');
                empty.className = 'sidebar-empty';
                empty.textContent = term
                    ? 'No chats matching "' + term + '"'
                    : 'No past chats yet.';
                sidebarList.appendChild(empty);
                return;
            }

            var lastGroup = null;
            convos.forEach(function (conv) {
                var when = dayBucket(conv.last_at || conv.created_at);

                if (when.label !== lastGroup) {
                    lastGroup = when.label;
                    var head = document.createElement('div');
                    head.className = 'sidebar-group';
                    head.textContent = when.label;
                    sidebarList.appendChild(head);
                }

                var item = document.createElement('div');
                item.className = 'sidebar-item' + (conv.id === conversationId ? ' active' : '');

                var body = '<span class="sidebar-item-main">' +
                    '<span class="sidebar-item-title">' +
                        highlight(oneLine(conv.title) || 'Untitled', term) + '</span>';
                if (conv.snippet) {
                    body += '<span class="sidebar-item-snippet">' +
                        highlight(oneLine(conv.snippet), term) + '</span>';
                }
                body += '<span class="sidebar-item-meta">' + escapeHtml(when.stamp) + '</span>';
                body += '</span>';

                item.innerHTML = body +
                    '<button class="sidebar-item-delete" title="Delete">&times;</button>';

                item.querySelector('.sidebar-item-main').addEventListener('click', function () {
                    loadConversation(conv.id);
                    closeSidebar();
                });
                item.querySelector('.sidebar-item-delete').addEventListener('click', function (e) {
                    e.stopPropagation();
                    deleteConversation(conv.id);
                });
                sidebarList.appendChild(item);
            });
        })
        .catch(function () {});
}

// ===== Sidebar Search =====
var searchInput = document.getElementById('sidebar-search-input');
var searchClear = document.getElementById('sidebar-search-clear');
var searchTimer = null;

if (searchInput) {
    searchInput.addEventListener('input', function () {
        // Debounced - searching message bodies touches every row, no need to
        // do it on each keystroke.
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
            searchTerm = searchInput.value.trim();
            searchClear.classList.toggle('visible', !!searchTerm);
            loadConversations();
        }, 220);
    });
    searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); }
    });
}
if (searchClear) {
    searchClear.addEventListener('click', function () {
        searchInput.value = '';
        searchTerm = '';
        searchClear.classList.remove('visible');
        loadConversations();
        searchInput.focus();
    });
}

// ===== Load Conversation =====
function loadConversation(id) {
    conversationId = id;
    fetch('/api/conversations/' + id + '/messages')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            welcomeScreen.style.display = 'none';
            // Remove all messages but keep welcome screen
            var messages = chatContainer.querySelectorAll('.message, .tool-indicator');
            messages.forEach(function (el) { el.remove(); });
            (data.messages || []).forEach(function (msg) {
                addMessage(msg.role, msg.content);
            });
            chatContainer.scrollTop = chatContainer.scrollHeight;
            // Update active sidebar item
            document.querySelectorAll('.sidebar-item').forEach(function (el) {
                el.classList.remove('active');
            });
            loadConversations();
        })
        .catch(function () {});
}

// ===== Delete Conversation =====
function deleteConversation(id) {
    fetch('/api/conversations/' + id, { method: 'DELETE' })
        .then(function () {
            if (conversationId === id) {
                conversationId = null;
                chatContainer.innerHTML = '';
                chatContainer.appendChild(welcomeScreen);
                welcomeScreen.style.display = '';
            }
            loadConversations();
        })
        .catch(function () {});
}

// ===== Load Dashboard =====
function loadDashboard() {
    fetch('/api/dashboard')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // The counts live under data.stats, not on data itself. Reading them
            // off the top level gave undefined every time, which is why all three
            // tiles sat on '--' no matter what the inbox held.
            var s = data.stats || {};
            statUnread.textContent = s.unread_emails !== undefined ? s.unread_emails : '--';
            statToday.textContent = s.today_events !== undefined ? s.today_events : '--';
            statTomorrow.textContent = s.tomorrow_events !== undefined ? s.tomorrow_events : '--';
            if (data.errors && data.errors.length) {
                console.warn('dashboard stats incomplete:', data.errors);
            }
        })
        .catch(function (err) { console.warn('dashboard fetch failed:', err); });
}

// ===== Auth Status =====
function checkAuthStatus() {
    fetch('/api/auth/status')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // Google
            if (data.google_connected) {
                statusDot.classList.add('connected');
                statusText.textContent = 'Connected';
                connectBtn.textContent = 'Disconnect Google';
                connectBtn.classList.add('connected');
            } else {
                statusDot.classList.remove('connected');
                statusText.textContent = 'Disconnected';
                connectBtn.textContent = 'Connect Google';
                connectBtn.classList.remove('connected');
            }
            // Meta
            if (data.meta_connected) {
                metaConnectBtn.textContent = 'Disconnect Meta';
                metaConnectBtn.classList.add('connected');
            } else {
                metaConnectBtn.textContent = 'Connect Meta';
                metaConnectBtn.classList.remove('connected');
            }
            // Lofty
            if (data.lofty_connected) {
                loftyConnectBtn.textContent = 'Lofty Connected';
                loftyConnectBtn.style.background = '#059669';
                loftyConnectBtn.onclick = disconnectLofty;
            } else {
                loftyConnectBtn.textContent = 'Connect Lofty';
                loftyConnectBtn.style.background = '#10b981';
                loftyConnectBtn.onclick = startLoftyAuth;
            }
        })
        .catch(function () {});
}

// ===== Google Auth Flow =====
connectBtn.addEventListener('click', function () {
    if (connectBtn.classList.contains('connected')) {
        disconnectGoogle();
    } else {
        googleStep1.style.display = '';
        googleStep2.style.display = 'none';
        googleAuthCode.value = '';
        googleAuthModal.classList.add('visible');
    }
});

googleModalClose.addEventListener('click', function () {
    googleAuthModal.classList.remove('visible');
});

function startGoogleAuth() {
    fetch('/api/auth/google')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.auth_url) {
                window.open(data.auth_url, '_blank');
                googleStep1.style.display = 'none';
                googleStep2.style.display = '';
            }
        })
        .catch(function () {});
}

googleAuthorizeBtn.addEventListener('click', startGoogleAuth);

function submitAuthCode() {
    var code = googleAuthCode.value.trim();
    if (!code) return;
    if (code.indexOf('code=') !== -1) {
        try {
            var url = new URL(code.replace('http://localhost', 'http://dummy'));
            code = url.searchParams.get('code') || code;
        } catch (e) {}
    }
    fetch('/api/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code })
    })
        .then(function (r) {
            if (r.ok) {
                googleAuthModal.classList.remove('visible');
                checkAuthStatus();
                loadDashboard();
            }
        })
        .catch(function () {});
}

googleSubmitBtn.addEventListener('click', submitAuthCode);

function disconnectGoogle() {
    fetch('/api/auth/disconnect', { method: 'POST' })
        .then(function () {
            checkAuthStatus();
        })
        .catch(function () {});
}

// ===== Meta Auth Flow =====
metaConnectBtn.addEventListener('click', function () {
    if (metaConnectBtn.classList.contains('connected')) {
        disconnectMeta();
    } else {
        metaStep1.style.display = '';
        metaStep2.style.display = 'none';
        metaAuthCode.value = '';
        metaAuthModal.classList.add('visible');
    }
});

metaModalClose.addEventListener('click', function () {
    metaAuthModal.classList.remove('visible');
});

function startMetaAuth() {
    fetch('/api/auth/meta/start', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.auth_url) {
                window.open(data.auth_url, '_blank');
                metaStep1.style.display = 'none';
                metaStep2.style.display = '';
            }
        })
        .catch(function () {});
}

metaAuthorizeBtn.addEventListener('click', startMetaAuth);

function submitMetaCode() {
    var redirectUrl = metaAuthCode.value.trim();
    if (!redirectUrl) return;
    // Extract code from the redirect URL
    var code = redirectUrl;
    try {
        var urlObj = new URL(redirectUrl);
        var codeParam = urlObj.searchParams.get('code');
        if (codeParam) code = codeParam;
    } catch (e) {
        // If not a valid URL, use as-is (might be just the code)
    }
    fetch('/api/auth/meta/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code })
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            metaAuthModal.classList.remove('visible');
            checkAuthStatus();
        })
        .catch(function () {});
}

metaSubmitBtn.addEventListener('click', submitMetaCode);

function disconnectMeta() {
    fetch('/api/auth/meta/disconnect', { method: 'POST' })
        .then(function () {
            checkAuthStatus();
        })
        .catch(function () {});
}

// ===== Lofty Auth Flow =====
function startLoftyAuth() {
    fetch('/api/auth/lofty')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.auth_url) {
                window.open(data.auth_url, '_blank');
                loftyAuthError.style.display = 'none';
                loftyAuthCode.value = '';
                loftyAuthModal.classList.add('visible');
            }
        });
}

loftyModalClose.addEventListener('click', function () {
    loftyAuthModal.classList.remove('visible');
});

loftySubmitBtn.addEventListener('click', submitLoftyCode);
loftyAuthCode.addEventListener('keydown', function (e) { if (e.key === 'Enter') submitLoftyCode(); });

function submitLoftyCode() {
    var code = loftyAuthCode.value.trim();
    if (!code) return;
    if (code.indexOf('code=') !== -1) {
        try {
            var url = new URL(code.replace('http://localhost', 'http://dummy'));
            code = url.searchParams.get('code') || code;
        } catch (e) {}
    }
    loftySubmitBtn.disabled = true;
    loftySubmitBtn.textContent = 'Connecting...';
    loftyAuthError.style.display = 'none';
    fetch('/api/auth/lofty/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code })
    })
        .then(function (r) {
            if (r.ok) {
                loftyAuthModal.classList.remove('visible');
                checkAuthStatus();
            } else {
                loftyAuthError.textContent = 'Connection failed. Please try again with a fresh code.';
                loftyAuthError.style.display = 'block';
            }
            loftySubmitBtn.disabled = false;
            loftySubmitBtn.textContent = 'Connect';
        })
        .catch(function () {
            loftyAuthError.textContent = 'Something went wrong.';
            loftyAuthError.style.display = 'block';
            loftySubmitBtn.disabled = false;
            loftySubmitBtn.textContent = 'Connect';
        });
}

function disconnectLofty() {
    fetch('/api/auth/lofty/disconnect', { method: 'POST' })
        .then(function () { checkAuthStatus(); });
}

// ===== HTML Escaping =====
function escapeHtml(text) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

// ===== Add Message =====
function addMessage(role, content, files) {
    welcomeScreen.style.display = 'none';

    var msgDiv = document.createElement('div');
    msgDiv.className = 'message ' + role;

    var avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? 'U' : 'AI';

    // Reloaded history carries the note that was appended for the assistant.
    // Hide the plumbing and draw the thumbnails back instead.
    if (role === 'user' && content) {
        var marker = content.match(/\n*\[The agent attached \d+ files?: ([^\]]+?)\. Already uploaded[\s\S]*?\]\s*$/);
        if (marker) {
            content = content.replace(marker[0], '');
            if (!files || !files.length) {
                files = marker[1].split(',').map(function (n) {
                    n = n.trim();
                    return {
                        filename: n,
                        url: '/api/uploads/' + encodeURIComponent(n),
                        kind: IMAGE_EXT.indexOf(extOf(n)) !== -1 ? 'image' : 'file'
                    };
                });
            }
        }
    }

    var contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = formatMarkdown(content);

    // Show what was attached in the bubble itself, so scrolling back tells you
    // which photo a graphic was built from.
    if (files && files.length) {
        var strip = document.createElement('div');
        strip.className = 'msg-photos';
        files.forEach(function (f) {
            if (f.kind === 'image') {
                var img = document.createElement('img');
                img.src = f.url;
                img.alt = f.filename;
                strip.appendChild(img);
            } else {
                var tag = document.createElement('div');
                tag.className = 'msg-file';
                tag.textContent = f.filename;
                strip.appendChild(tag);
            }
        });
        contentDiv.appendChild(strip);
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    return contentDiv;
}

// ===== Tool Indicator =====
function addToolIndicator(toolName, detail) {
    var div = document.createElement('div');
    div.className = 'tool-indicator';

    var displayName = toolNames[toolName] || toolName;
    var detailHtml = detail ? '<span class="tool-detail">' + escapeHtml(detail) + '</span>' : '';

    div.innerHTML =
        '<div class="spinner"></div>' +
        '<span class="tool-name">' + escapeHtml(displayName) + '</span>' +
        detailHtml;

    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

// ===== Mark Tool Done =====
function markToolDone(indicator) {
    if (!indicator) return;
    indicator.classList.add('done');
    var spinner = indicator.querySelector('.spinner');
    if (spinner) {
        spinner.outerHTML = '<span class="checkmark">&#10003;</span>';
    }
}

// ===== Format Markdown =====
function formatMarkdown(text) {
    if (!text) return '';

    // HTML escape first
    var html = escapeHtml(text);

    // Code blocks
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, function (match, lang, code) {
        return '<pre><code>' + code.trim() + '</code></pre>';
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Markdown links [text](url) - handle possible line breaks between ] and (
    html = html.replace(/\[([^\]]+)\]\s*\n?\s*\(([^)]+)\)/g, function (match, linkText, url) {
        var cleanUrl = url.replace(/&amp;/g, '&');
        return '<a href="' + cleanUrl + '" target="_blank" rel="noopener">' + linkText + '</a>';
    });

    // Raw URLs (not already in href)
    html = html.replace(/(^|[^"=])(https?:\/\/[^\s<]+)/g, function (match, prefix, url) {
        var cleanUrl = url.replace(/&amp;/g, '&');
        return prefix + '<a href="' + cleanUrl + '" target="_blank" rel="noopener">' + url + '</a>';
    });

    // Unordered lists
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // Ordered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // Paragraphs: split by double newlines
    var parts = html.split(/\n\n+/);
    html = parts.map(function (part) {
        part = part.trim();
        if (!part) return '';
        if (part.startsWith('<pre>') || part.startsWith('<ul>') || part.startsWith('<ol>') || part.startsWith('<li>')) {
            return part;
        }
        return '<p>' + part + '</p>';
    }).join('');

    // Single line breaks within paragraphs
    html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');

    return html;
}

// ===== Attachments =====
// The backend has taken uploads since day one - there was just no way to reach
// it from the chat. Files upload the moment they are picked, so send is instant.
var attachBtn = document.getElementById('attach-btn');
var fileInput = document.getElementById('file-input');
var attachStrip = document.getElementById('attach-strip');
var dropVeil = document.getElementById('drop-veil');
var attachments = [];
var IMAGE_EXT = ['jpg', 'jpeg', 'png', 'webp'];

function extOf(name) {
    var bits = String(name || '').split('.');
    return bits.length > 1 ? bits.pop().toLowerCase() : '';
}

function renderAttachStrip() {
    attachStrip.innerHTML = '';
    attachStrip.classList.toggle('has-files', attachments.length > 0);

    attachments.forEach(function (f, i) {
        var chip = document.createElement('div');
        chip.className = 'attach-chip' + (f.status ? ' ' + f.status : '');

        if (f.kind === 'image' && f.url) {
            var img = document.createElement('img');
            img.src = f.url;
            img.alt = f.filename;
            chip.appendChild(img);
        } else {
            var glyph = document.createElement('div');
            glyph.className = 'chip-glyph';
            glyph.textContent = (extOf(f.filename) || 'FILE').toUpperCase().slice(0, 4);
            chip.appendChild(glyph);
        }

        var name = document.createElement('span');
        name.className = 'chip-name';
        name.textContent = f.status === 'uploading' ? 'Uploading...'
            : (f.status === 'failed' ? (f.error || 'Upload failed') : f.filename);
        chip.appendChild(name);

        var remove = document.createElement('button');
        remove.className = 'chip-remove';
        remove.type = 'button';
        remove.innerHTML = '&times;';
        remove.title = 'Remove';
        remove.addEventListener('click', function () { removeAttachment(i); });
        chip.appendChild(remove);

        attachStrip.appendChild(chip);
    });
}

function removeAttachment(i) {
    var f = attachments[i];
    attachments.splice(i, 1);
    renderAttachStrip();
    // Drop it from the server too, so removing a wrong photo does not leave it
    // sitting in the list the assistant can pick from.
    if (f && f.status === 'done' && f.filename) {
        fetch('/api/uploads/' + encodeURIComponent(f.filename), { method: 'DELETE' })
            .catch(function () { });
    }
}

function uploadFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;

    files.forEach(function (file) {
        var placeholder = {
            filename: file.name,
            kind: IMAGE_EXT.indexOf(extOf(file.name)) !== -1 ? 'image' : 'file',
            url: '',
            status: 'uploading'
        };
        attachments.push(placeholder);
        renderAttachStrip();

        var form = new FormData();
        form.append('files', file);

        fetch('/api/uploads', { method: 'POST', body: form })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok) throw new Error(data.detail || ('Upload failed (' + r.status + ')'));
                    return data;
                });
            })
            .then(function (data) {
                var saved = (data.uploaded || [])[0];
                if (!saved) throw new Error('Upload failed');
                placeholder.filename = saved.filename;
                placeholder.url = saved.url;
                placeholder.kind = saved.kind || placeholder.kind;
                placeholder.status = 'done';
                renderAttachStrip();
            })
            .catch(function (err) {
                placeholder.status = 'failed';
                placeholder.error = String(err.message || err).slice(0, 80);
                renderAttachStrip();
            });
    });
}

attachBtn.addEventListener('click', function () { fileInput.click(); });

fileInput.addEventListener('change', function () {
    uploadFiles(fileInput.files);
    fileInput.value = '';   // so picking the same file twice still fires
});

// Paste a screenshot straight into the box
messageInput.addEventListener('paste', function (e) {
    var items = (e.clipboardData && e.clipboardData.files) || [];
    if (items.length) {
        e.preventDefault();
        uploadFiles(items);
    }
});

// Drag and drop anywhere on the page
var dragDepth = 0;
window.addEventListener('dragenter', function (e) {
    if (!e.dataTransfer || e.dataTransfer.types.indexOf('Files') === -1) return;
    dragDepth++;
    dropVeil.classList.add('show');
});
window.addEventListener('dragleave', function () {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropVeil.classList.remove('show');
});
window.addEventListener('dragover', function (e) { e.preventDefault(); });
window.addEventListener('drop', function (e) {
    e.preventDefault();
    dragDepth = 0;
    dropVeil.classList.remove('show');
    if (e.dataTransfer && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});

// ===== Send Message =====
function sendMessage() {
    var text = messageInput.value.trim();
    var ready = attachments.filter(function (f) { return f.status === 'done'; });
    if ((!text && !ready.length) || isStreaming) return;
    if (attachments.some(function (f) { return f.status === 'uploading'; })) return;

    // Tell the assistant the filenames. They are already on the server, so it
    // must use them directly - never send the agent off to find a photo.
    var payload = text;
    if (ready.length) {
        var names = ready.map(function (f) { return f.filename; }).join(', ');
        payload = (text ? text + '\n\n' : '') +
            '[The agent attached ' + ready.length + ' file' + (ready.length > 1 ? 's' : '') +
            ': ' + names + '. Already uploaded to REAI. Pass an image filename straight ' +
            'into create_marketing_graphic as the photo, or use read_document for a PDF, ' +
            'TXT or CSV. Do not ask the agent to upload, link or fetch it again.]';
    }

    isStreaming = true;
    sendBtn.disabled = true;
    messageInput.value = '';
    messageInput.style.height = 'auto';
    attachments = [];
    renderAttachStrip();

    addMessage('user', text, ready);

    var currentToolIndicator = null;
    var assistantContentDiv = null;
    var assistantText = '';

    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: payload,
            conversation_id: conversationId
        })
    }).then(function (response) {
        if (!response.ok) {
            throw new Error('Server returned ' + response.status);
        }
        if (!response.body) {
            throw new Error('No response body');
        }
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function processChunk(result) {
            if (result.done) {
                if (!assistantContentDiv && !currentToolIndicator) {
                    addMessage('assistant', 'No response received. Please try again.');
                }
                isStreaming = false;
                sendBtn.disabled = false;
                loadConversations();
                return;
            }

            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();

            lines.forEach(function (line) {
                if (!line.startsWith('data: ')) return;
                var data;
                try {
                    data = JSON.parse(line.substring(6));
                } catch (e) {
                    return;
                }

                switch (data.type) {
                    case 'conversation_id':
                        conversationId = data.id;
                        break;

                    case 'tool_start':
                        currentToolIndicator = addToolIndicator(data.tool, data.detail || '');
                        break;

                    case 'tool_done':
                        markToolDone(currentToolIndicator);
                        currentToolIndicator = null;
                        break;

                    case 'text':
                        if (!assistantContentDiv) {
                            assistantContentDiv = addMessage('assistant', '');
                            assistantText = '';
                        }
                        assistantText += data.content;
                        assistantContentDiv.innerHTML = formatMarkdown(assistantText);
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                        break;

                    case 'error':
                        addMessage('assistant', 'Error: ' + (data.content || 'Something went wrong'));
                        break;

                    case 'done':
                        isStreaming = false;
                        sendBtn.disabled = false;
                        loadConversations();
                        // A reply that drafted a post should show the Approve
                        // card straight away, not up to 15s later.
                        loadPendingPosts();
                        break;
                }
            });

            return reader.read().then(processChunk);
        }

        return reader.read().then(processChunk);
    }).catch(function (err) {
        isStreaming = false;
        sendBtn.disabled = false;
        addMessage('assistant', 'Connection error - please refresh the page and try again.');
    });
}

sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ===== Suggestion Cards =====
function useSuggestion(text) {
    messageInput.value = text;
    sendMessage();
}

// ===== Auto-resize Textarea =====
messageInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// ===== Pending social posts =====
// The assistant drafts; only a click here publishes. It has no tool that can
// reach Facebook or Instagram, so this button is the only way out.
var pendingBar = document.getElementById('pending-bar');

function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// The bar is fixed, like the header and the chat area, so it would sit on top
// of the conversation. Push the chat down by however tall the bar actually is.
function reflowForPending() {
    var chat = document.getElementById('chat-container');
    if (!chat) return;
    var visible = pendingBar.style.display !== 'none';
    chat.style.top = visible ? (56 + pendingBar.offsetHeight) + 'px' : '';
}

function loadPendingPosts() {
    fetch('/api/pending-posts')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var rows = data.pending || [];
            if (!rows.length) {
                pendingBar.style.display = 'none';
                pendingBar.innerHTML = '';
                reflowForPending();
                return;
            }
            pendingBar.innerHTML = rows.map(function (p) {
                var img = p.image_url
                    ? '<img src="' + escapeHtml(p.image_url) + '" alt="">'
                    : '';
                return '<div class="pending-card" data-id="' + p.id + '">' + img +
                    '<div class="pending-body">' +
                    '<div class="pending-title">' + escapeHtml(p.platform) +
                    ' &middot; waiting for your approval</div>' +
                    '<div class="pending-caption">' + escapeHtml(p.caption) + '</div>' +
                    '<div class="pending-actions">' +
                    '<button class="btn-approve" data-act="publish" data-id="' + p.id + '">Approve &amp; Post</button>' +
                    '<button class="btn-discard" data-act="discard" data-id="' + p.id + '">Discard</button>' +
                    '</div></div></div>';
            }).join('');
            pendingBar.style.display = 'block';
            reflowForPending();
        })
        .catch(function () {});
}

window.addEventListener('resize', reflowForPending);

pendingBar.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-act]');
    if (!btn) return;
    var act = btn.dataset.act;
    if (act === 'publish' && !confirm('Post this to your page now?')) return;

    var card = btn.closest('.pending-card');
    card.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
    btn.textContent = act === 'publish' ? 'Posting...' : 'Discarding...';

    fetch('/api/pending-posts/' + btn.dataset.id + '/' + act, { method: 'POST' })
        .then(function (r) {
            return r.json().then(function (body) {
                if (!r.ok) throw new Error(body.detail || 'That did not work.');
                return body;
            });
        })
        .then(function () { loadPendingPosts(); })
        .catch(function (err) {
            alert(err.message);
            loadPendingPosts();
        });
});

// ===== Initialization =====
checkAuthStatus();
loadConversations();
loadDashboard();
loadPendingPosts();

// Periodic refresh
setInterval(checkAuthStatus, 30000);
setInterval(loadDashboard, 60000);
setInterval(loadPendingPosts, 15000);
