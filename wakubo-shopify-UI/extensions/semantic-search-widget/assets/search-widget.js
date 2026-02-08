(function() {
  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function init() {
    const container = document.getElementById('semantic-search-float');
    const fab = document.getElementById('search-fab');
    const panel = document.getElementById('search-panel');
    const minimizeBtn = document.getElementById('minimize-btn');
    const searchBtn = document.getElementById('search-btn');
    const searchInput = document.getElementById('search-input');
    const cameraInput = document.getElementById('camera-input');
    const resultsContainer = document.getElementById('search-results');
    
    if (!container) return;
    
    // Enhance theme detection from DOM if not provided by Liquid
    enhanceThemeDetection(container);
    detectThemeIcons();
    
    const apiEndpoint = searchBtn?.dataset.api;
    
    // Toggle expand/minimize
    fab?.addEventListener('click', () => {
      container.classList.remove('semantic-search-minimized');
    });
    
    minimizeBtn?.addEventListener('click', () => {
      container.classList.add('semantic-search-minimized');
    });
    
    // Make draggable
    makeDraggable(panel, document.getElementById('search-drag-handle'));
    
    // Text search
    searchBtn?.addEventListener('click', handleTextSearch);
    searchInput?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') handleTextSearch();
    });
    
    // Image search
    cameraInput?.addEventListener('change', handleImageSearch);
    
    // Theme detection enhancement
    function enhanceThemeDetection(container) {
      // Read existing CSS variables or compute from document
      const computedStyle = getComputedStyle(document.documentElement);
      const bodyStyle = getComputedStyle(document.body);
      
      // Try to detect primary color from common theme patterns
      if (!container.dataset.themePrimary || container.dataset.themePrimary === '#667eea') {
        // Check for common CSS variables
        const primaryColor = 
          computedStyle.getPropertyValue('--color-primary').trim() ||
          computedStyle.getPropertyValue('--primary-color').trim() ||
          computedStyle.getPropertyValue('--accent-color').trim() ||
          extractColorFromElement('a') || // Link color often is brand color
          extractColorFromElement('button') ||
          container.dataset.themePrimary;
        
        if (primaryColor) {
          container.style.setProperty('--theme-primary', primaryColor);
        }
      }
      
      // Detect text color
      if (!container.dataset.themeText) {
        const textColor = 
          computedStyle.getPropertyValue('--color-text').trim() ||
          bodyStyle.color ||
          container.dataset.themeText;
        
        if (textColor) {
          container.style.setProperty('--theme-text', textColor);
        }
      }
      
      // Detect background color
      if (!container.dataset.themeBg) {
        const bgColor = 
          computedStyle.getPropertyValue('--color-background').trim() ||
          bodyStyle.backgroundColor ||
          container.dataset.themeBg;
        
        if (bgColor) {
          container.style.setProperty('--theme-bg', bgColor);
        }
      }
      
      // Detect fonts
      const headingFont = 
        computedStyle.getPropertyValue('--font-heading').trim() ||
        getComputedStyle(document.querySelector('h1, h2, h3')).fontFamily ||
        container.dataset.fontHeading;
      
      const bodyFont = 
        computedStyle.getPropertyValue('--font-body').trim() ||
        bodyStyle.fontFamily ||
        container.dataset.fontBody;
      
      if (headingFont) {
        container.style.setProperty('--font-heading', headingFont);
      }
      
      if (bodyFont) {
        container.style.setProperty('--font-body', bodyFont);
      }
    }

    function extractColorFromElement(selector) {
      const element = document.querySelector(selector);
      if (!element) return null;
      
      const style = getComputedStyle(element);
      return style.backgroundColor !== 'rgba(0, 0, 0, 0)' 
        ? style.backgroundColor 
        : style.color;
    }

    function extractColorFromElement(selector) {
      const element = document.querySelector(selector);
      if (!element) return null;
      
      const style = getComputedStyle(element);
      return style.backgroundColor !== 'rgba(0, 0, 0, 0)' 
        ? style.backgroundColor 
        : style.color;
    }
    
    function detectThemeIcons() {
      // Try to find search icon in theme
      const themeSearchIcon = document.querySelector('.header__search svg, .predictive-search svg, button[aria-label*="Search" i] svg');
      if (themeSearchIcon) {
        const fabIconContainer = document.querySelector('.fab-icon-container');
        if (fabIconContainer) {
          const clone = themeSearchIcon.cloneNode(true);
          fabIconContainer.appendChild(clone);
        }
      }
      
      // Try to find camera/upload icon in theme
      const themeCameraIcon = document.querySelector('svg[class*="camera"], svg[class*="upload"], input[type="file"] + label svg');
      if (themeCameraIcon) {
        const cameraIconContainer = document.querySelector('.camera-icon-container');
        if (cameraIconContainer) {
          const clone = themeCameraIcon.cloneNode(true);
          cameraIconContainer.appendChild(clone);
        }
      }
    }
    
    async function handleTextSearch() {
      const query = searchInput.value.trim();
      if (!query) return;
      
      resultsContainer.innerHTML = '<div class="search-loading">Searching...</div>';
      
      try {
        const formData = new FormData();
        formData.append('query', query);
        
        const response = await fetch(`${apiEndpoint}/api/search/text`, {
          method: 'POST',
          body: formData
        });
        
        const data = await response.json();
        displayResults(data.products);
      } catch (error) {
        resultsContainer.innerHTML = '<div class="search-error">Search failed. Check backend connection.</div>';
        console.error('Search error:', error);
      }
    }
    
    async function handleImageSearch(e) {
      const file = e.target.files[0];
      if (!file) return;
      
      resultsContainer.innerHTML = '<div class="search-loading">Analyzing image...</div>';
      
      try {
        const formData = new FormData();
        formData.append('image', file);
        
        const response = await fetch(`${apiEndpoint}/api/search/image`, {
          method: 'POST',
          body: formData
        });
        
        const data = await response.json();
        
        if (data.products && data.products.length > 0) {
          window.location.href = data.products[0].product_url;
        } else {
          displayResults([]);
        }
      } catch (error) {
        resultsContainer.innerHTML = '<div class="search-error">Image search failed.</div>';
        console.error('Image search error:', error);
      }
    }
    
    function displayResults(products) {
      if (!products || products.length === 0) {
        resultsContainer.innerHTML = '<div class="search-empty">No products found.</div>';
        return;
      }
      
      resultsContainer.innerHTML = products.map(p => `
        <div class="product-result">
          <h4>${p.title || 'Untitled'}</h4>
          <p>${(p.description || '').substring(0, 80)}${p.description?.length > 80 ? '...' : ''}</p>
          <span class="price">$${p.price || '0.00'}</span><br>
          <a href="${p.product_url || '#'}">View Product →</a>
        </div>
      `).join('');
    }
    
    // Drag functionality (unchanged from previous version)
    function makeDraggable(element, handle) {
      if (!element || !handle) return;
      
      let isDragging = false;
      let currentX = 0;
      let currentY = 0;
      let initialX = 0;
      let initialY = 0;
      
      handle.addEventListener('mousedown', dragStart);
      handle.addEventListener('touchstart', dragStart);
      
      function dragStart(e) {
        e.preventDefault();
        isDragging = true;
        
        if (e.type === 'touchstart') {
          initialX = e.touches[0].clientX;
          initialY = e.touches[0].clientY;
        } else {
          initialX = e.clientX;
          initialY = e.clientY;
        }
        
        const rect = element.getBoundingClientRect();
        currentX = rect.left;
        currentY = rect.top;
        
        element.style.right = 'auto';
        element.style.bottom = 'auto';
        element.style.left = currentX + 'px';
        element.style.top = currentY + 'px';
        
        document.addEventListener('mousemove', drag);
        document.addEventListener('mouseup', dragEnd);
        document.addEventListener('touchmove', drag);
        document.addEventListener('touchend', dragEnd);
        
        handle.style.cursor = 'grabbing';
      }
      
      function drag(e) {
        if (!isDragging) return;
        e.preventDefault();
        
        let clientX, clientY;
        
        if (e.type === 'touchmove') {
          clientX = e.touches[0].clientX;
          clientY = e.touches[0].clientY;
        } else {
          clientX = e.clientX;
          clientY = e.clientY;
        }
        
        const deltaX = clientX - initialX;
        const deltaY = clientY - initialY;
        
        let newX = currentX + deltaX;
        let newY = currentY + deltaY;
        
        const rect = element.getBoundingClientRect();
        const minX = 0;
        const minY = 0;
        const maxX = window.innerWidth - rect.width;
        const maxY = window.innerHeight - rect.height;
        
        newX = Math.max(minX, Math.min(newX, maxX));
        newY = Math.max(minY, Math.min(newY, maxY));
        
        element.style.left = newX + 'px';
        element.style.top = newY + 'px';
      }
      
      function dragEnd() {
        isDragging = false;
        document.removeEventListener('mousemove', drag);
        document.removeEventListener('mouseup', dragEnd);
        document.removeEventListener('touchmove', drag);
        document.removeEventListener('touchend', dragEnd);
        handle.style.cursor = 'move';
      }
    }
  }
})();
