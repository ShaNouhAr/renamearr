/**
 * Renamearr - Frontend Application
 * Avec Server-Sent Events pour mises à jour temps réel
 */

// State
let currentFiles = [];
let groupedMedia = [];
let expandedGroups = {};  // {key: true}
let expandedSeasons = {}; // {key_season: true}
let selectedFile = null;
let selectedTmdbResult = null;
let searchTimeout = null;
let currentBrowserPath = '/mnt';
let browserTargetField = null;
let currentSourceMode = 'unified';
let eventSource = null;
let isScanning = false;

// API Base URL
const API_BASE = '/api';

// ============================================
// Initialization
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    // Charger les infos utilisateur
    loadUserInfo();
    
    loadStats();
    loadFiles();
    loadConfig();
    
    // Initialiser SSE pour les mises à jour temps réel
    initSSE();
    
    // Cacher le dropdown quand on clique ailleurs
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.user-menu')) {
            document.getElementById('user-dropdown')?.classList.remove('visible');
        }
    });
    
    // Event listener pour le checkbox auto-scan
    const autoScanCheckbox = document.getElementById('config-auto-scan');
    if (autoScanCheckbox) {
        autoScanCheckbox.addEventListener('change', updateAutoScanIntervalVisibility);
    }
    
    // Rafraîchir le statut de l'auto-scan toutes les 30 secondes
    setInterval(loadAutoScanStatus, 30000);
});

// ============================================
// Authentication
// ============================================

function loadUserInfo() {
    // Récupérer les infos depuis localStorage (définies à la connexion)
    const username = localStorage.getItem('username') || 'Admin';
    const passwordChanged = localStorage.getItem('password_changed');
    
    // Afficher le nom d'utilisateur
    const usernameEl = document.getElementById('current-username');
    if (usernameEl) {
        usernameEl.textContent = username;
    }
    
    // Afficher l'avertissement si mot de passe par défaut
    if (passwordChanged === 'false') {
        const warningBanner = document.getElementById('password-warning');
        if (warningBanner) {
            warningBanner.style.display = 'flex';
        }
    }
}

function toggleUserMenu() {
    const dropdown = document.getElementById('user-dropdown');
    dropdown.classList.toggle('visible');
}

function hidePasswordWarning() {
    const warningBanner = document.getElementById('password-warning');
    if (warningBanner) {
        warningBanner.style.display = 'none';
    }
}

function openChangePassword() {
    document.getElementById('user-dropdown')?.classList.remove('visible');
    document.getElementById('password-modal').classList.add('active');
    document.getElementById('new-password-change').value = '';
    document.getElementById('confirm-password-change').value = '';
}

function closePasswordModal() {
    document.getElementById('password-modal').classList.remove('active');
}

async function changePassword() {
    const newPassword = document.getElementById('new-password-change').value;
    const confirmPassword = document.getElementById('confirm-password-change').value;
    
    if (!newPassword || !confirmPassword) {
        showToast('Veuillez remplir tous les champs', 'error');
        return;
    }
    
    if (newPassword !== confirmPassword) {
        showToast('Les mots de passe ne correspondent pas', 'error');
        return;
    }
    
    if (newPassword.length < 4) {
        showToast('Le mot de passe doit faire au moins 4 caractères', 'error');
        return;
    }
    
    try {
        await api('/auth/change-password', {
            method: 'POST',
            body: JSON.stringify({ new_password: newPassword })
        });
        
        // Mettre à jour le localStorage
        localStorage.setItem('password_changed', 'true');
        
        // Cacher l'avertissement
        hidePasswordWarning();
        
        closePasswordModal();
        showToast('Mot de passe changé avec succès', 'success');
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

async function logout() {
    try {
        await api('/auth/logout', { method: 'POST' });
    } catch (e) {
        // Ignorer les erreurs
    }
    
    // Nettoyer le localStorage
    localStorage.removeItem('auth_token');
    localStorage.removeItem('username');
    localStorage.removeItem('password_changed');
    
    // Rediriger vers la page de connexion
    window.location.href = '/login';
}

// ============================================
// Users Management
// ============================================

async function loadUsers() {
    try {
        const users = await api('/auth/users');
        renderUsers(users);
    } catch (error) {
        console.error('Erreur chargement utilisateurs:', error);
    }
}

function renderUsers(users) {
    const container = document.getElementById('users-list');
    if (!container) return;
    
    if (users.length === 0) {
        container.innerHTML = '<p class="empty-state">Aucun utilisateur</p>';
        return;
    }
    
    container.innerHTML = users.map(user => `
        <div class="user-item" data-id="${user.id}">
            <div class="user-info">
                <div class="user-avatar">${user.username.charAt(0).toUpperCase()}</div>
                <div class="user-details">
                    <span class="user-name">
                        ${escapeHtml(user.username)}
                        <span class="user-badge admin">Admin</span>
                        ${!user.password_changed ? '<span class="user-badge warning">MDP par défaut</span>' : ''}
                    </span>
                    <span class="user-meta">Créé le ${new Date(user.created_at).toLocaleDateString('fr-FR')}</span>
                </div>
            </div>
            <div class="user-actions">
                <button class="btn btn-sm btn-ghost" onclick="resetUserPassword(${user.id}, '${escapeHtml(user.username)}')" title="Réinitialiser mot de passe">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                    </svg>
                </button>
                <button class="btn btn-sm btn-ghost btn-danger-ghost" onclick="deleteUser(${user.id}, '${escapeHtml(user.username)}')" title="Supprimer">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                </button>
            </div>
        </div>
    `).join('');
}

async function createUser() {
    const username = document.getElementById('new-username').value.trim();
    const password = document.getElementById('new-password').value;
    
    if (!username || !password) {
        showToast('Veuillez remplir tous les champs', 'error');
        return;
    }
    
    if (password.length < 4) {
        showToast('Le mot de passe doit faire au moins 4 caractères', 'error');
        return;
    }
    
    try {
        await api('/auth/users', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
        
        // Vider les champs
        document.getElementById('new-username').value = '';
        document.getElementById('new-password').value = '';
        
        showToast(`Utilisateur ${username} créé`, 'success');
        loadUsers();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer l'utilisateur "${username}" ?`)) {
        return;
    }
    
    try {
        await api(`/auth/users/${userId}`, { method: 'DELETE' });
        showToast(`Utilisateur ${username} supprimé`, 'success');
        loadUsers();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

async function resetUserPassword(userId, username) {
    const newPassword = prompt(`Nouveau mot de passe pour ${username}:`);
    
    if (!newPassword) return;
    
    if (newPassword.length < 4) {
        showToast('Le mot de passe doit faire au moins 4 caractères', 'error');
        return;
    }
    
    try {
        await api(`/auth/users/${userId}/reset-password`, {
            method: 'POST',
            body: JSON.stringify({ new_password: newPassword })
        });
        showToast(`Mot de passe de ${username} réinitialisé`, 'success');
        loadUsers();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

// ============================================
// Server-Sent Events (SSE) - Temps réel
// ============================================

function initSSE() {
    if (eventSource) {
        eventSource.close();
    }
    
    eventSource = new EventSource('/api/events');
    
    eventSource.onopen = () => {
        console.log('SSE connecté');
    };
    
    eventSource.onerror = (e) => {
        console.error('SSE erreur, reconnexion...', e);
        setTimeout(initSSE, 3000);
    };
    
    eventSource.onmessage = (event) => {
        try {
            const { type, data } = JSON.parse(event.data);
            handleSSEEvent(type, data);
        } catch (e) {
            console.error('Erreur parsing SSE:', e);
        }
    };
}

function handleSSEEvent(type, data) {
    console.log('SSE Event:', type, data);
    
    switch (type) {
        case 'file_added':
            handleFileAdded(data);
            break;
        case 'file_updated':
            handleFileUpdated(data);
            break;
        case 'file_deleted':
            handleFileDeleted(data);
            break;
        case 'stats_updated':
            handleStatsUpdated(data);
            break;
        case 'scan_started':
            handleScanStarted();
            break;
        case 'scan_progress':
            handleScanProgress(data);
            break;
        case 'scan_completed':
            handleScanCompleted(data);
            break;
    }
}

// Debounce pour recharger les fichiers groupés
let reloadGroupedTimeout = null;

function handleFileAdded(fileData) {
    // Recharger la vue groupée avec debounce
    clearTimeout(reloadGroupedTimeout);
    reloadGroupedTimeout = setTimeout(() => loadFiles(), 500);
}

function handleFileUpdated(fileData) {
    // Recharger la vue groupée avec debounce
    clearTimeout(reloadGroupedTimeout);
    reloadGroupedTimeout = setTimeout(() => loadFiles(), 500);
}

function handleFileDeleted(data) {
    // Recharger la vue groupée avec debounce
    clearTimeout(reloadGroupedTimeout);
    reloadGroupedTimeout = setTimeout(() => loadFiles(), 500);
}

function handleStatsUpdated(stats) {
    // Mettre à jour les compteurs principaux
    const statTotal = document.getElementById('stat-total');
    const statPending = document.getElementById('stat-pending');
    const statLinked = document.getElementById('stat-linked');
    const statManual = document.getElementById('stat-manual');
    const statFailed = document.getElementById('stat-failed');
    
    if (statTotal) animateCounter(statTotal, stats.total_files);
    if (statPending) animateCounter(statPending, stats.pending);
    if (statLinked) animateCounter(statLinked, stats.linked);
    if (statManual) animateCounter(statManual, stats.manual);
    if (statFailed) animateCounter(statFailed, stats.failed);
    
    // Mettre à jour les compteurs détaillés (films/séries)
    updateDetailCounter('stat-movies-total', stats.movies_total);
    updateDetailCounter('stat-tv-total', stats.tv_total);
    
    updateDetailCounter('stat-pending-movies', stats.pending_movies);
    updateDetailCounter('stat-pending-tv', stats.pending_tv);
    
    updateDetailCounter('stat-linked-movies', stats.linked_movies);
    updateDetailCounter('stat-linked-tv', stats.linked_tv);
    
    updateDetailCounter('stat-manual-movies', stats.manual_movies);
    updateDetailCounter('stat-manual-tv', stats.manual_tv);
    
    updateDetailCounter('stat-failed-movies', stats.failed_movies);
    updateDetailCounter('stat-failed-tv', stats.failed_tv);
    
    // Si la base est vide, vider l'affichage des fichiers
    if (stats.total_files === 0) {
        currentFiles = [];
        const container = document.getElementById('files-list');
        if (container) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <p>Aucun fichier trouvé</p>
                    <p>Lancez un scan pour commencer</p>
                </div>
            `;
        }
    }
}

function updateDetailCounter(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        const currentValue = parseInt(element.textContent) || 0;
        if (currentValue !== value) {
            element.textContent = value || 0;
            element.classList.add('counter-updated');
            setTimeout(() => element.classList.remove('counter-updated'), 300);
        }
    }
}

function animateCounter(element, newValue) {
    const currentValue = parseInt(element.textContent) || 0;
    if (currentValue !== newValue) {
        element.textContent = newValue;
        element.classList.add('counter-updated');
        setTimeout(() => element.classList.remove('counter-updated'), 300);
    }
}

function handleScanStarted() {
    isScanning = true;
    showToast('Scan démarré...', 'info');
    
    // Afficher indicateur de scan
    const scanBtn = document.querySelector('.header-right .btn-primary');
    if (scanBtn) {
        scanBtn.disabled = true;
        scanBtn.innerHTML = `
            <div class="spinner-small"></div>
            Scan en cours...
        `;
    }
}

function handleScanProgress(data) {
    // Mettre à jour la progression dans le toast ou ailleurs
    const { current, total, filename } = data;
    console.log(`Scan: ${current}/${total} - ${filename}`);
}

function handleScanCompleted(stats) {
    isScanning = false;
    showToast(`Scan terminé: ${stats.new} nouveaux, ${stats.linked} liés`, 'success');
    
    // Restaurer le bouton
    const scanBtn = document.querySelector('.header-right .btn-primary');
    if (scanBtn) {
        scanBtn.disabled = false;
        scanBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                <path d="M21 3v5h-5"/>
            </svg>
            Scanner
        `;
    }
}

// ============================================
// Tab Navigation
// ============================================

function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });
    
    // Reload data if needed
    if (tabName === 'config') {
        loadConfig();
    } else if (tabName === 'users') {
        loadUsers();
    }
}

// ============================================
// API Calls
// ============================================

async function api(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Une erreur est survenue');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// ============================================
// Stats
// ============================================

async function loadStats() {
    try {
        const stats = await api('/stats');
        
        // Compteurs principaux
        document.getElementById('stat-total').textContent = stats.total_files;
        document.getElementById('stat-pending').textContent = stats.pending;
        document.getElementById('stat-linked').textContent = stats.linked;
        document.getElementById('stat-manual').textContent = stats.manual;
        document.getElementById('stat-failed').textContent = stats.failed;
        
        // Compteurs détaillés films/séries
        setDetailCounter('stat-movies-total', stats.movies_total);
        setDetailCounter('stat-tv-total', stats.tv_total);
        
        setDetailCounter('stat-pending-movies', stats.pending_movies);
        setDetailCounter('stat-pending-tv', stats.pending_tv);
        
        setDetailCounter('stat-linked-movies', stats.linked_movies);
        setDetailCounter('stat-linked-tv', stats.linked_tv);
        
        setDetailCounter('stat-manual-movies', stats.manual_movies);
        setDetailCounter('stat-manual-tv', stats.manual_tv);
        
        setDetailCounter('stat-failed-movies', stats.failed_movies);
        setDetailCounter('stat-failed-tv', stats.failed_tv);
    } catch (error) {
        showToast('Erreur lors du chargement des statistiques', 'error');
    }
}

function setDetailCounter(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = value || 0;
    }
}

// ============================================
// Files - Vue Groupée
// ============================================

async function loadFiles() {
    const statusEl = document.getElementById('filter-status');
    const typeEl = document.getElementById('filter-type');
    const searchEl = document.getElementById('search-input');
    
    // Vérifier que les éléments existent
    if (!statusEl || !typeEl || !searchEl) {
        return;
    }
    
    const status = statusEl.value;
    const mediaType = typeEl.value;
    const search = searchEl.value;
    
    const container = document.getElementById('files-list');
    if (!container) return;
    
    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    
    try {
        // Utiliser l'endpoint groupé
        let url = `/files/grouped?_t=${Date.now()}`;
        if (status) url += `&status=${status}`;
        if (mediaType) url += `&media_type=${mediaType}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        groupedMedia = await api(url);
        renderGroupedFiles();
    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="m15 9-6 6"/>
                    <path d="m9 9 6 6"/>
                </svg>
                <h3>Erreur de chargement</h3>
                <p>${error.message}</p>
            </div>
        `;
    }
}

function renderGroupedFiles() {
    const container = document.getElementById('files-list');
    
    if (groupedMedia.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 15V6"/>
                    <path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/>
                    <path d="M12 12H3"/>
                    <path d="M16 6H3"/>
                    <path d="M12 18H3"/>
                </svg>
                <h3>Aucun fichier</h3>
                <p>Lancez un scan pour détecter les fichiers médias</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = groupedMedia.map(media => renderMediaGroup(media)).join('');
}

function renderMediaGroup(media) {
    const isExpanded = expandedGroups[media.key];
    
    const poster = media.poster 
        ? `<img src="${media.poster}" alt="Poster" loading="lazy">`
        : `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
             <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
             <line x1="7" y1="2" x2="7" y2="22"/>
             <line x1="17" y1="2" x2="17" y2="22"/>
             <line x1="2" y1="12" x2="22" y2="12"/>
           </svg>`;
    
    // Déterminer le statut global
    let statusClass = 'linked';
    let statusText = 'Tous liés';
    if (media.failed_files > 0) {
        statusClass = 'failed';
        statusText = `${media.failed_files} échec(s)`;
    } else if (media.manual_files > 0) {
        statusClass = 'manual';
        statusText = `${media.manual_files} manuel(s)`;
    } else if (media.pending_files > 0) {
        statusClass = 'pending';
        statusText = `${media.pending_files} en attente`;
    }
    
    // Info sur le contenu
    let contentInfo = '';
    if (media.media_type === 'tv' && media.seasons) {
        const seasonCount = Object.keys(media.seasons).length;
        contentInfo = `${seasonCount} saison${seasonCount > 1 ? 's' : ''} · ${media.total_files} épisode${media.total_files > 1 ? 's' : ''}`;
    } else {
        contentInfo = `${media.total_files} fichier${media.total_files > 1 ? 's' : ''}`;
    }
    
    // Contenu déplié
    let expandedContent = '';
    if (isExpanded) {
        if (media.media_type === 'tv' && media.seasons) {
            expandedContent = renderSeasons(media);
        } else if (media.files) {
            expandedContent = renderMovieFiles(media.files);
        }
    }
    
    return `
        <div class="media-group ${isExpanded ? 'expanded' : ''}" data-key="${media.key}">
            <div class="media-group-header" onclick="toggleMediaGroup('${media.key}')">
                <div class="media-group-poster">${poster}</div>
                <div class="media-group-info">
                    <div class="media-group-title">${escapeHtml(media.title)}</div>
                    <div class="media-group-meta">
                        <span class="badge badge-${media.media_type}">${getMediaTypeLabel(media.media_type)}</span>
                        ${media.year ? `<span class="badge">${media.year}</span>` : ''}
                        <span class="media-group-count">${contentInfo}</span>
                    </div>
                    <div class="media-group-status">
                        <span class="status-dot status-${statusClass}"></span>
                        <span class="status-label">${media.linked_files}/${media.total_files} liés</span>
                        ${statusClass !== 'linked' ? `<span class="badge badge-${statusClass}">${statusText}</span>` : ''}
                    </div>
                </div>
                <div class="media-group-chevron">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </div>
            </div>
            <div class="media-group-content">
                ${expandedContent}
            </div>
        </div>
    `;
}

function renderSeasons(media) {
    const seasons = Object.entries(media.seasons);
    
    return seasons.map(([seasonNum, episodes]) => {
        const seasonKey = `${media.key}_s${seasonNum}`;
        const isSeasonExpanded = expandedSeasons[seasonKey];
        const linkedCount = episodes.filter(e => e.status === 'linked').length;
        
        // Statut de la saison
        let seasonStatus = 'linked';
        if (episodes.some(e => e.status === 'failed')) seasonStatus = 'failed';
        else if (episodes.some(e => e.status === 'manual')) seasonStatus = 'manual';
        else if (episodes.some(e => e.status === 'pending')) seasonStatus = 'pending';
        
        const seasonTitle = seasonNum == 0 ? 'Spéciaux' : `Saison ${seasonNum}`;
        
        return `
            <div class="season-group ${isSeasonExpanded ? 'expanded' : ''}" data-season="${seasonNum}">
                <div class="season-header" onclick="event.stopPropagation(); toggleSeason('${seasonKey}', '${media.key}')">
                    <div class="season-info">
                        <span class="status-dot status-${seasonStatus}"></span>
                        <span class="season-title">${seasonTitle}</span>
                        <span class="season-count">${episodes.length} épisode${episodes.length > 1 ? 's' : ''}</span>
                    </div>
                    <div class="season-right">
                        <span class="season-progress">${linkedCount}/${episodes.length}</span>
                        <div class="season-chevron">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="6 9 12 15 18 9"/>
                            </svg>
                        </div>
                    </div>
                </div>
                <div class="season-episodes">
                    ${isSeasonExpanded ? renderEpisodes(episodes) : ''}
                </div>
            </div>
        `;
    }).join('');
}

function renderEpisodes(episodes) {
    return episodes.map(ep => `
        <div class="episode-item" data-id="${ep.id}">
            <div class="episode-info">
                <span class="episode-number">E${String(ep.episode || 0).padStart(2, '0')}</span>
                <span class="episode-filename" title="${escapeHtml(ep.source_path)}">${escapeHtml(ep.source_filename)}</span>
            </div>
            <span class="badge badge-${ep.status}">${getStatusLabel(ep.status)}</span>
            <div class="episode-actions">
                ${renderFileActions({id: ep.id, status: ep.status})}
            </div>
        </div>
    `).join('');
}

function renderMovieFiles(files) {
    return `
        <div class="movie-files">
            ${files.map(file => `
                <div class="movie-file-item" data-id="${file.id}">
                    <div class="file-info-row">
                        <span class="filename" title="${escapeHtml(file.source_path)}">${escapeHtml(file.source_filename)}</span>
                        <span class="badge badge-${file.status}">${getStatusLabel(file.status)}</span>
                    </div>
                    <div class="file-actions-row">
                        ${renderFileActions({id: file.id, status: file.status})}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function toggleMediaGroup(key) {
    expandedGroups[key] = !expandedGroups[key];
    renderGroupedFiles();
}

function toggleSeason(seasonKey, mediaKey) {
    expandedSeasons[seasonKey] = !expandedSeasons[seasonKey];
    renderGroupedFiles();
}

// Ancienne fonction pour compatibilité
function renderFiles() {
    renderGroupedFiles();
}

function renderFileItem(file) {
    const poster = file.tmdb_poster 
        ? `<img src="${file.tmdb_poster}" alt="Poster" loading="lazy">`
        : `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
             <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
             <line x1="7" y1="2" x2="7" y2="22"/>
             <line x1="17" y1="2" x2="17" y2="22"/>
             <line x1="2" y1="12" x2="22" y2="12"/>
             <line x1="2" y1="7" x2="7" y2="7"/>
             <line x1="2" y1="17" x2="7" y2="17"/>
             <line x1="17" y1="17" x2="22" y2="17"/>
             <line x1="17" y1="7" x2="22" y2="7"/>
           </svg>`;
    
    const title = file.tmdb_title || file.parsed_title || file.source_filename;
    const year = file.tmdb_year || file.parsed_year;
    const yearBadge = year ? `<span class="badge">${year}</span>` : '';
    
    const seasonEpisode = file.media_type === 'tv' && file.parsed_season !== null
        ? `<span class="badge">S${String(file.parsed_season).padStart(2, '0')}E${String(file.parsed_episode || 0).padStart(2, '0')}</span>`
        : '';
    
    return `
        <div class="file-item" data-id="${file.id}">
            <div class="file-poster">${poster}</div>
            <div class="file-info">
                <div class="file-title">${escapeHtml(title)}</div>
                <div class="file-original" title="${escapeHtml(file.source_path)}">${escapeHtml(file.source_filename)}</div>
                <div class="file-meta">
                    <span class="badge badge-${file.media_type}">${getMediaTypeLabel(file.media_type)}</span>
                    <span class="badge badge-${file.status}">${getStatusLabel(file.status)}</span>
                    ${yearBadge}
                    ${seasonEpisode}
                </div>
                ${file.error_message ? `<div class="file-original" style="color: var(--error);">${escapeHtml(file.error_message)}</div>` : ''}
            </div>
            <div class="file-actions">
                ${renderFileActions(file)}
            </div>
        </div>
    `;
}

function renderFileActions(file) {
    const actions = [];
    
    // Bouton de correction manuelle pour les fichiers non liés
    if (['pending', 'manual', 'failed'].includes(file.status)) {
        actions.push(`
            <button class="btn btn-primary btn-xs" onclick="event.stopPropagation(); openManualMatchById(${file.id})" title="Corriger">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
            </button>
        `);
    }
    
    // Bouton retraiter
    if (['failed', 'manual', 'matched'].includes(file.status)) {
        actions.push(`
            <button class="btn btn-secondary btn-xs" onclick="event.stopPropagation(); reprocessFile(${file.id})" title="Retraiter">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                    <path d="M21 3v5h-5"/>
                </svg>
            </button>
        `);
    }
    
    // Bouton ignorer
    if (!['ignored', 'linked'].includes(file.status)) {
        actions.push(`
            <button class="btn btn-ghost btn-xs" onclick="event.stopPropagation(); ignoreFile(${file.id})" title="Ignorer">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
                </svg>
            </button>
        `);
    }
    
    return actions.join('');
}

// ============================================
// Actions
// ============================================

async function scanFiles() {
    if (isScanning) {
        showToast('Un scan est déjà en cours', 'warning');
        return;
    }
    
    // Basculer sur l'onglet fichiers pour voir les mises à jour en direct
    switchTab('files');
    
    try {
        // Le scan sera géré via SSE pour les mises à jour en temps réel
        await api('/scan', { method: 'POST' });
        // Les événements SSE géreront les notifications et mises à jour
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
        isScanning = false;
        
        // Restaurer le bouton en cas d'erreur
        const scanBtn = document.querySelector('.header-right .btn-primary');
        if (scanBtn) {
            scanBtn.disabled = false;
            scanBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                    <path d="M21 3v5h-5"/>
                </svg>
                Scanner
            `;
        }
    }
}

async function refreshData() {
    // Rafraîchir stats et liste de fichiers
    console.log('Refreshing data...');
    try {
        // Charger stats
        await loadStats();
        
        // Si on est sur l'onglet fichiers, rafraîchir la liste
        const filesTab = document.getElementById('tab-files');
        if (filesTab && filesTab.classList.contains('active')) {
            await loadFiles();
        }
        
        console.log('Data refreshed successfully');
    } catch (error) {
        console.error('Refresh error:', error);
    }
}

async function reprocessFile(fileId) {
    try {
        await api(`/files/${fileId}/reprocess`, { method: 'POST' });
        showToast('Fichier retraité', 'success');
        await loadStats();
        await loadFiles();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

async function ignoreFile(fileId) {
    try {
        await api(`/files/${fileId}/ignore`, { method: 'POST' });
        showToast('Fichier ignoré', 'success');
        await loadStats();
        await loadFiles();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

// ============================================
// Wipe Database
// ============================================

function confirmWipe() {
    if (confirm('⚠️ ATTENTION ⚠️\n\nCette action va :\n- Supprimer TOUS les fichiers de la base de données\n- Supprimer TOUS les liens créés (hardlinks/symlinks)\n\nLes fichiers sources ne seront pas affectés.\n\nÊtes-vous sûr de vouloir continuer ?')) {
        if (confirm('Dernière confirmation : voulez-vous vraiment tout supprimer ?')) {
            wipeDatabase();
        }
    }
}

async function wipeDatabase() {
    try {
        showToast('Suppression en cours...', 'info');
        const result = await api('/wipe', { method: 'POST' });
        showToast(`Base vidée: ${result.links_removed} liens supprimés`, 'success');
        
        // Vider la liste locale
        currentFiles = [];
        
        // Basculer sur l'onglet fichiers et vider l'affichage
        switchTab('files');
        const container = document.getElementById('files-list');
        if (container) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <p>Aucun fichier trouvé</p>
                    <p>Lancez un scan pour commencer</p>
                </div>
            `;
        }
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

// ============================================
// Manual Match Modal
// ============================================

async function openManualMatchById(fileId) {
    try {
        const file = await api(`/files/${fileId}`);
        if (file) {
            openManualMatchWithFile(file);
        }
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

async function openManualMatch(fileId) {
    const file = currentFiles.find(f => f.id === fileId);
    if (!file) {
        return openManualMatchById(fileId);
    }
    openManualMatchWithFile(file);
}

function openManualMatchWithFile(file) {
    selectedFile = file;
    selectedTmdbResult = null;
    
    const modal = document.getElementById('modal-overlay');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    
    title.textContent = 'Correction manuelle';
    body.innerHTML = `
        <div class="modal-form">
            <div class="form-group">
                <label>Fichier source</label>
                <input type="text" value="${escapeHtml(file.source_filename)}" disabled>
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label>Type de média</label>
                    <select id="match-type" onchange="onMediaTypeChange()">
                        <option value="movie" ${file.media_type === 'movie' ? 'selected' : ''}>Film</option>
                        <option value="tv" ${file.media_type === 'tv' ? 'selected' : ''}>Série</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Année (optionnel)</label>
                    <input type="number" id="match-year" value="${file.parsed_year || ''}" placeholder="2024">
                </div>
            </div>
            
            <div id="season-episode-fields" style="display: ${file.media_type === 'tv' ? 'block' : 'none'};">
                <div class="form-row">
                    <div class="form-group">
                        <label>Saison</label>
                        <input type="number" id="match-season" value="${file.parsed_season || 1}" min="0">
                    </div>
                    <div class="form-group">
                        <label>Épisode</label>
                        <input type="number" id="match-episode" value="${file.parsed_episode || 1}" min="0">
                    </div>
                </div>
            </div>
            
            <div class="form-group">
                <label>Rechercher sur TMDB</label>
                <input type="text" id="match-search" value="${escapeHtml(file.parsed_title || '')}" 
                       placeholder="Titre du film ou de la série" onkeyup="debounceSearchTmdb()">
            </div>
            
            <div id="tmdb-results" class="tmdb-results">
                <!-- Résultats TMDB -->
            </div>
            
            <div style="display: flex; gap: var(--spacing-md); justify-content: flex-end; margin-top: var(--spacing-md);">
                <button class="btn btn-secondary" onclick="closeModal()">Annuler</button>
                <button class="btn btn-primary" onclick="submitManualMatch()" id="submit-match-btn" disabled>
                    Appliquer
                </button>
            </div>
        </div>
    `;
    
    modal.classList.add('active');
    
    // Rechercher automatiquement avec le titre parsé
    if (file.parsed_title) {
        searchTmdb();
    }
}

function onMediaTypeChange() {
    const type = document.getElementById('match-type').value;
    const fields = document.getElementById('season-episode-fields');
    fields.style.display = type === 'tv' ? 'block' : 'none';
    
    // Relancer la recherche avec le nouveau type
    searchTmdb();
}

let tmdbSearchTimeout = null;
function debounceSearchTmdb() {
    clearTimeout(tmdbSearchTimeout);
    tmdbSearchTimeout = setTimeout(searchTmdb, 300);
}

async function searchTmdb() {
    const query = document.getElementById('match-search').value;
    const year = document.getElementById('match-year').value;
    const type = document.getElementById('match-type').value;
    
    if (!query) {
        document.getElementById('tmdb-results').innerHTML = '';
        return;
    }
    
    try {
        let url = `/tmdb/search?query=${encodeURIComponent(query)}&media_type=${type}`;
        if (year) url += `&year=${year}`;
        
        const results = await api(url);
        renderTmdbResults(results);
    } catch (error) {
        document.getElementById('tmdb-results').innerHTML = `
            <p style="color: var(--error);">Erreur de recherche: ${error.message}</p>
        `;
    }
}

function renderTmdbResults(results) {
    const container = document.getElementById('tmdb-results');
    
    if (results.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted);">Aucun résultat trouvé</p>';
        return;
    }
    
    container.innerHTML = results.map(result => `
        <div class="tmdb-result" onclick="selectTmdbResult(${result.id}, '${result.media_type}')" 
             data-id="${result.id}" data-type="${result.media_type}">
            <div class="tmdb-result-poster">
                ${result.poster_path 
                    ? `<img src="${result.poster_path}" alt="Poster" loading="lazy">`
                    : ''}
            </div>
            <div class="tmdb-result-info">
                <div class="tmdb-result-title">${escapeHtml(result.title)}</div>
                <div class="tmdb-result-year">
                    ${result.year || 'N/A'} · 
                    <span class="badge badge-${result.media_type}">${getMediaTypeLabel(result.media_type)}</span>
                </div>
                <div class="tmdb-result-overview">${escapeHtml(result.overview || '')}</div>
            </div>
        </div>
    `).join('');
}

function selectTmdbResult(tmdbId, mediaType) {
    // Désélectionner l'ancien
    document.querySelectorAll('.tmdb-result').forEach(el => el.classList.remove('selected'));
    
    // Sélectionner le nouveau
    const selected = document.querySelector(`.tmdb-result[data-id="${tmdbId}"]`);
    if (selected) {
        selected.classList.add('selected');
    }
    
    selectedTmdbResult = { id: tmdbId, media_type: mediaType };
    
    // Mettre à jour le type si différent
    document.getElementById('match-type').value = mediaType;
    onMediaTypeChange();
    
    // Activer le bouton
    document.getElementById('submit-match-btn').disabled = false;
}

async function submitManualMatch() {
    if (!selectedFile || !selectedTmdbResult) return;
    
    const mediaType = document.getElementById('match-type').value;
    const season = document.getElementById('match-season')?.value;
    const episode = document.getElementById('match-episode')?.value;
    
    try {
        const body = {
            file_id: selectedFile.id,
            tmdb_id: selectedTmdbResult.id,
            media_type: mediaType,
        };
        
        if (mediaType === 'tv') {
            body.season = parseInt(season) || 1;
            body.episode = parseInt(episode) || 1;
        }
        
        await api(`/files/${selectedFile.id}/match`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        
        showToast('Correspondance appliquée avec succès', 'success');
        closeModal();
        await loadStats();
        await loadFiles();
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
    selectedFile = null;
    selectedTmdbResult = null;
}

// ============================================
// Search Debounce
// ============================================

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadFiles, 300);
}

// ============================================
// Toast Notifications
// ============================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span>${escapeHtml(message)}</span>
    `;
    
    container.appendChild(toast);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ============================================
// Utilities
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getMediaTypeLabel(type) {
    switch (type) {
        case 'movie': return 'Film';
        case 'tv': return 'Série';
        default: return 'Inconnu';
    }
}

function getStatusLabel(status) {
    switch (status) {
        case 'pending': return 'En attente';
        case 'matched': return 'Correspondance';
        case 'linked': return 'Lié';
        case 'manual': return 'Manuel';
        case 'failed': return 'Échec';
        case 'ignored': return 'Ignoré';
        default: return status;
    }
}

// Format file size
function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ============================================
// Configuration
// ============================================

async function loadConfig() {
    try {
        const config = await api('/config');
        
        // Mode
        currentSourceMode = config.source_mode || 'unified';
        setSourceMode(currentSourceMode, false);
        
        // Chemins sources
        document.getElementById('config-source-path').value = config.source_path || '';
        document.getElementById('config-source-movies-path').value = config.source_movies_path || '';
        document.getElementById('config-source-tv-path').value = config.source_tv_path || '';
        
        // Chemins destinations
        document.getElementById('config-movies-path').value = config.movies_path || '';
        document.getElementById('config-tv-path').value = config.tv_path || '';
        
        // Radarr
        document.getElementById('config-radarr-url').value = config.radarr_url || '';
        document.getElementById('config-radarr-api').value = config.radarr_api_key || '';
        
        // Sonarr
        document.getElementById('config-sonarr-url').value = config.sonarr_url || '';
        document.getElementById('config-sonarr-api').value = config.sonarr_api_key || '';
        
        // Validation
        document.getElementById('config-require-arr').checked = config.require_arr || false;
        
        // Auto-scan
        document.getElementById('config-auto-scan').checked = config.auto_scan_enabled || false;
        document.getElementById('config-auto-scan-interval').value = config.auto_scan_interval || 30;
        document.getElementById('config-auto-scan-unit').value = config.auto_scan_unit || 'minutes';
        updateAutoScanIntervalVisibility();
        
        // Options
        document.getElementById('config-tmdb-language').value = config.tmdb_language || 'fr-FR';
        document.getElementById('config-min-size').value = config.min_video_size_mb || 50;
        
        // Charger le statut de l'auto-scan
        loadAutoScanStatus();
    } catch (error) {
        showToast('Erreur lors du chargement de la configuration', 'error');
    }
}

function updateAutoScanIntervalVisibility() {
    const enabled = document.getElementById('config-auto-scan').checked;
    const field = document.getElementById('auto-scan-interval-field');
    if (field) {
        field.style.opacity = enabled ? '1' : '0.5';
    }
}

async function loadAutoScanStatus() {
    try {
        const status = await api('/auto-scan/status');
        const container = document.getElementById('auto-scan-status');
        if (!container) return;
        
        let statusHtml = '';
        if (status.enabled) {
            if (status.next_scan) {
                const nextScan = new Date(status.next_scan);
                const now = new Date();
                const diffMs = nextScan - now;
                const diffSecs = Math.max(0, Math.round(diffMs / 1000));
                
                let timeLabel;
                if (diffSecs < 60) {
                    timeLabel = `${diffSecs}s`;
                } else if (diffSecs < 3600) {
                    timeLabel = `${Math.round(diffSecs / 60)} min`;
                } else {
                    timeLabel = `${Math.round(diffSecs / 3600)}h`;
                }
                
                statusHtml = `
                    <span class="status-dot status-linked"></span>
                    <span>Auto-scan actif · Prochain dans ${timeLabel}</span>
                `;
            } else {
                statusHtml = `
                    <span class="status-dot status-pending"></span>
                    <span>Auto-scan actif · En attente...</span>
                `;
            }
            if (status.last_scan) {
                const lastScan = new Date(status.last_scan);
                statusHtml += `<span class="auto-scan-last">Dernier: ${lastScan.toLocaleTimeString('fr-FR')}</span>`;
            }
        } else {
            statusHtml = `
                <span class="status-dot status-manual"></span>
                <span>Auto-scan désactivé</span>
            `;
        }
        container.innerHTML = statusHtml;
    } catch (error) {
        console.error('Erreur chargement statut auto-scan:', error);
    }
}

function setSourceMode(mode, animate = true) {
    currentSourceMode = mode;
    
    // Mettre à jour les boutons
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    
    // Afficher/cacher les sections appropriées
    const unifiedSection = document.getElementById('source-unified');
    const separateSection = document.getElementById('source-separate');
    
    if (mode === 'unified') {
        unifiedSection.style.display = 'block';
        separateSection.style.display = 'none';
    } else {
        unifiedSection.style.display = 'none';
        separateSection.style.display = 'block';
    }
}

async function saveConfig() {
    const autoScanInterval = parseInt(document.getElementById('config-auto-scan-interval').value) || 30;
    const autoScanUnit = document.getElementById('config-auto-scan-unit').value;
    
    // Valider l'intervalle
    if (autoScanInterval < 5) {
        showToast('L\'intervalle doit être au minimum 5', 'error');
        return;
    }
    
    const config = {
        source_mode: currentSourceMode,
        source_path: document.getElementById('config-source-path').value,
        source_movies_path: document.getElementById('config-source-movies-path').value,
        source_tv_path: document.getElementById('config-source-tv-path').value,
        movies_path: document.getElementById('config-movies-path').value,
        tv_path: document.getElementById('config-tv-path').value,
        radarr_url: document.getElementById('config-radarr-url').value,
        radarr_api_key: document.getElementById('config-radarr-api').value,
        sonarr_url: document.getElementById('config-sonarr-url').value,
        sonarr_api_key: document.getElementById('config-sonarr-api').value,
        require_arr: document.getElementById('config-require-arr').checked,
        auto_scan_enabled: document.getElementById('config-auto-scan').checked,
        auto_scan_interval: autoScanInterval,
        auto_scan_unit: autoScanUnit,
        tmdb_language: document.getElementById('config-tmdb-language').value,
        min_video_size_mb: parseInt(document.getElementById('config-min-size').value) || 50,
    };
    
    try {
        await api('/config', {
            method: 'PUT',
            body: JSON.stringify(config),
        });
        showToast('Configuration sauvegardée', 'success');
        
        // Recharger le statut de l'auto-scan
        setTimeout(loadAutoScanStatus, 1000);
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

// ============================================
// Radarr / Sonarr Tests
// ============================================

async function testRadarr() {
    const status = document.getElementById('radarr-status');
    status.textContent = 'Test en cours...';
    status.className = 'connection-status loading';
    
    // Sauvegarder d'abord pour que l'API ait les bonnes valeurs
    await saveConfig();
    
    try {
        const result = await api('/config/test-radarr', { method: 'POST' });
        status.textContent = result.message;
        status.className = `connection-status ${result.success ? 'success' : 'error'}`;
    } catch (error) {
        status.textContent = `Erreur: ${error.message}`;
        status.className = 'connection-status error';
    }
}

async function testSonarr() {
    const status = document.getElementById('sonarr-status');
    status.textContent = 'Test en cours...';
    status.className = 'connection-status loading';
    
    // Sauvegarder d'abord pour que l'API ait les bonnes valeurs
    await saveConfig();
    
    try {
        const result = await api('/config/test-sonarr', { method: 'POST' });
        status.textContent = result.message;
        status.className = `connection-status ${result.success ? 'success' : 'error'}`;
    } catch (error) {
        status.textContent = `Erreur: ${error.message}`;
        status.className = 'connection-status error';
    }
}

// ============================================
// Directory Browser
// ============================================

function openBrowser(targetField) {
    browserTargetField = targetField;
    
    // Toujours démarrer sur /mnt pour une navigation facile
    currentBrowserPath = '/mnt';
    
    document.getElementById('browser-modal').classList.add('active');
    loadBrowserDirectory(currentBrowserPath);
}

function closeBrowser() {
    document.getElementById('browser-modal').classList.remove('active');
    browserTargetField = null;
}

async function loadBrowserDirectory(path) {
    currentBrowserPath = path;
    document.getElementById('browser-current-path').textContent = path;
    
    const container = document.getElementById('browser-list');
    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    
    try {
        const items = await api(`/browse?path=${encodeURIComponent(path)}`);
        
        container.innerHTML = items.map(item => `
            <div class="browser-item ${item.is_dir ? 'folder' : 'file'}" 
                 onclick="${item.is_dir ? `loadBrowserDirectory('${escapeHtml(item.path)}')` : ''}">
                ${item.is_dir ? `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                    </svg>
                ` : `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                `}
                <span>${escapeHtml(item.name)}</span>
            </div>
        `).join('');
        
    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <p style="color: var(--error);">Erreur: ${error.message}</p>
            </div>
        `;
    }
}

function selectCurrentPath() {
    if (!browserTargetField) return;
    
    const fieldMap = {
        'source_path': 'config-source-path',
        'source_movies_path': 'config-source-movies-path',
        'source_tv_path': 'config-source-tv-path',
        'movies_path': 'config-movies-path',
        'tv_path': 'config-tv-path',
    };
    
    const inputId = fieldMap[browserTargetField];
    document.getElementById(inputId).value = currentBrowserPath;
    
    closeBrowser();
}

// ============================================
// Create Folder
// ============================================

function showCreateFolder() {
    document.getElementById('create-folder-form').style.display = 'flex';
    document.getElementById('new-folder-name').value = '';
    document.getElementById('new-folder-name').focus();
}

function hideCreateFolder() {
    document.getElementById('create-folder-form').style.display = 'none';
    document.getElementById('new-folder-name').value = '';
}

function handleFolderNameKeyup(event) {
    if (event.key === 'Enter') {
        createFolder();
    } else if (event.key === 'Escape') {
        hideCreateFolder();
    }
}

async function createFolder() {
    const name = document.getElementById('new-folder-name').value.trim();
    
    if (!name) {
        showToast('Veuillez entrer un nom de dossier', 'warning');
        return;
    }
    
    try {
        await api('/browse/create', {
            method: 'POST',
            body: JSON.stringify({
                path: currentBrowserPath,
                name: name
            }),
        });
        
        showToast(`Dossier "${name}" créé`, 'success');
        hideCreateFolder();
        
        // Recharger le contenu du dossier actuel
        loadBrowserDirectory(currentBrowserPath);
        
    } catch (error) {
        showToast(`Erreur: ${error.message}`, 'error');
    }
}
