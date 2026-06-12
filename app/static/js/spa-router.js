/**
 * SPA Router for instant page transitions without full reload.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Initial setup for the first loaded page
    updateActiveSidebarLink(window.location.pathname);
    
    // Add global progress bar container to body
    const progressContainer = document.createElement('div');
    progressContainer.id = 'spa-progress';
    progressContainer.style.position = 'fixed';
    progressContainer.style.top = '0';
    progressContainer.style.left = '0';
    progressContainer.style.width = '0%';
    progressContainer.style.height = '3px';
    progressContainer.style.backgroundColor = 'var(--primary, #2563eb)';
    progressContainer.style.transition = 'width 0.2s ease, opacity 0.2s ease';
    progressContainer.style.zIndex = '9999';
    progressContainer.style.opacity = '0';
    progressContainer.style.pointerEvents = 'none';
    document.body.appendChild(progressContainer);
});

// Intercept clicks on links
document.addEventListener('click', async (e) => {
    // Only intercept left clicks without modifier keys
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;

    // Find the closest anchor tag
    const link = e.target.closest('a');
    if (!link) return;

    const href = link.getAttribute('href');
    
    // Skip if no href, external link, hash link, or download link
    if (!href || 
        href.startsWith('http') || 
        href.startsWith('//') || 
        href.startsWith('#') || 
        href.startsWith('javascript:') ||
        link.hasAttribute('download') ||
        link.getAttribute('target') === '_blank') {
        return;
    }
    
    // Intercept nav links or internal routing
    if (link.classList.contains('nav-link') || href.startsWith('/desktop/')) {
        
        // Let logout/login be normal full-page transitions
        if (href === '/logout' || href === '/login' || href === '/profile') return;
        
        e.preventDefault();
        navigateTo(href);
    }
});

// Handle Back/Forward buttons
window.addEventListener('popstate', () => {
    navigateTo(window.location.pathname + window.location.search, false);
});

async function navigateTo(url, pushState = true) {
    const mainContent = document.querySelector('.main-content .container');
    const progressBar = document.getElementById('spa-progress');
    
    if (!mainContent) {
        window.location.href = url; // fallback
        return;
    }

    try {
        // Show progress bar & fade out slightly
        progressBar.style.opacity = '1';
        progressBar.style.width = '30%';
        mainContent.style.transition = 'opacity 0.2s ease';
        mainContent.style.opacity = '0.5';
        
        // Update URL and Active Link immediately for UI responsiveness
        if (pushState) {
            history.pushState(null, '', url);
        }
        updateActiveSidebarLink(new URL(url, window.location.origin).pathname);

        const response = await fetch(url);
        progressBar.style.width = '70%';
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // If server redirects (e.g., to login), follow the redirect physically
        if (response.redirected) {
            window.location.href = response.url;
            return;
        }

        const html = await response.text();
        
        // Parse the new HTML
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        const newTitle = doc.querySelector('title')?.innerText || 'Склад';
        const newContent = doc.querySelector('.main-content .container');
        
        if (!newContent) {
            throw new Error("Target container not found in fetched HTML.");
        }

        // Apply new content
        document.title = newTitle;
        mainContent.innerHTML = newContent.innerHTML;
        
        // Ensure any scripts are executed in the global context
        executeScripts(mainContent);
        
        // Finish progress
        progressBar.style.width = '100%';
        mainContent.style.opacity = '1';
        
        setTimeout(() => {
            progressBar.style.opacity = '0';
            setTimeout(() => { progressBar.style.width = '0%'; }, 200);
        }, 300);
        
        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
        
        // Custom DOM event if any page-specific JS needs to know it just loaded
        document.dispatchEvent(new Event('spa:navigated'));
        
    } catch (error) {
        console.error('SPA Navigation Error:', error);
        // Fallback to traditional reload on error
        window.location.href = url;
    }
}

function updateActiveSidebarLink(pathname) {
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.classList.remove('active');
        const href = link.getAttribute('href');
        if (href === pathname || 
           (pathname === '/desktop/' && href === '/desktop/dashboard') ||
           (pathname === '/' && href === '/desktop/dashboard')) {
            link.classList.add('active');
        }
    });
}

function executeScripts(container) {
    const scripts = container.querySelectorAll('script');
    scripts.forEach(oldScript => {
        const newScript = document.createElement('script');
        
        Array.from(oldScript.attributes).forEach(attr => {
            newScript.setAttribute(attr.name, attr.value);
        });
        
        if (oldScript.innerHTML) {
            newScript.innerHTML = oldScript.innerHTML;
        }
        
        oldScript.parentNode.replaceChild(newScript, oldScript);
    });
}
