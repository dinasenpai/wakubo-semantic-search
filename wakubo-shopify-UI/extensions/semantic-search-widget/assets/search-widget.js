(function () {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.addEventListener('pageshow', function(e) {
    if (e.persisted) {
      // Page was restored from bfcache, re-run the intercept + panel restore
      checkSearchPageIntercept();
    }
  });

  function init() {
    const container = document.getElementById('semantic-search-float');
    const panel = document.getElementById('search-panel');
    const searchBtn = document.getElementById('search-btn');
    const cameraBtn = document.getElementById('camera-btn');
    const searchInput = document.getElementById('search-input');
    const cameraInput = document.getElementById('camera-input');
    const resultsContainer = document.getElementById('search-results');

    if (!container || !panel || !searchBtn || !cameraBtn || !searchInput || !cameraInput || !resultsContainer) return;

    container.classList.add('semantic-search-minimized');

    enhanceThemeDetection(container);

    const apiEndpoint = searchBtn.dataset.api;

    checkSearchPageIntercept();
    setupNativeSearchOverlay();

    searchBtn.addEventListener('click', handleTextSearch);
    searchInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') handleTextSearch();
    });

    cameraBtn.addEventListener('click', () => {
      cameraInput.click();
    });

    cameraInput.addEventListener('change', handleImageSearch);

    

    // -----------------------------
    // UI overlay logic
    // -----------------------------
    function setupNativeSearchOverlay() {
      let overlayBtn = document.getElementById('wakubo-search-overlay-btn');
      if (!overlayBtn) {
        overlayBtn = document.createElement('button');
        overlayBtn.id = 'wakubo-search-overlay-btn';
        overlayBtn.type = 'button';
        overlayBtn.setAttribute('aria-label', 'Search');
        document.body.appendChild(overlayBtn);
      }

      let fallbackBtn = document.getElementById('wakubo-fallback-btn');
      if (!fallbackBtn) {
        fallbackBtn = document.createElement('button');
        fallbackBtn.id = 'wakubo-fallback-btn';
        fallbackBtn.type = 'button';
        fallbackBtn.setAttribute('aria-label', 'Search');
        fallbackBtn.textContent = '\uD83D\uDD0D';
        document.body.appendChild(fallbackBtn);
      }

      let currentNativeBtn = null;
      let raf = null;
      let lastOpenTs = 0;
      let lastNativeSeenTs = 0;
      let lastNativeRect = null;
      let pendingNativeBtn = null;
      let pendingNativeSince = 0;
      let suppressAutoUpdateUntil = 0;
      const ANCHOR_STABILITY_MS = 120;
      const OPEN_CLOSE_GUARD_MS = 250;
      const NATIVE_STABILITY_MS = 900;
      const boundTriggerEls = new WeakSet();
      const boundInputEls = new WeakSet();
      const boundForms = new WeakSet();

      function scheduleUpdate() {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = null;
          update();
        });
      }

      function setDisplay(el, value) {
        el.style.setProperty('display', value, 'important');
      }

      function lockFloatingStyles(el) {
        if (!el) return;
        el.style.setProperty('position', 'fixed', 'important');
        el.style.setProperty('z-index', '2147483647', 'important');
      }

      function isExcluded(el) {
        return (
          !el ||
          el.id === 'wakubo-search-overlay-btn' ||
          el.id === 'wakubo-fallback-btn' ||
          container.contains(el)
        );
      }

      function normalizePath(pathname) {
        return (pathname || '').replace(/\/+$/, '') || '/';
      }

      function isSearchPath(value) {
        if (!value) return false;
        try {
          const parsed = new URL(value, window.location.origin);
          const path = normalizePath(parsed.pathname).toLowerCase();
          return path === '/search' || /\/search$/.test(path);
        } catch (e) {
          return false;
        }
      }

      function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          style.opacity === '0' ||
          style.pointerEvents === 'none'
        ) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        if (rect.bottom <= 0 || rect.right <= 0) return false;
        return true;
      }

      function isSearchForm(form) {
        if (!form) return false;
        const role = (form.getAttribute('role') || '').toLowerCase();
        if (role === 'search') return true;
        const action = form.getAttribute('action') || form.action || '';
        return isSearchPath(action);
      }

      function readFormQuery(form) {
        if (!form) return '';
        const queryInput = form.querySelector(
          'input[name="q"], input[type="search"], input[id*="search" i], input[placeholder*="search" i]'
        );
        return queryInput && typeof queryInput.value === 'string' ? queryInput.value.trim() : '';
      }

      function readQueryFromElement(el) {
        if (!el) return '';
        if (el.tagName && el.tagName.toLowerCase() === 'input' && typeof el.value === 'string') {
          return el.value.trim();
        }
        const form = el.closest ? el.closest('form') : null;
        return readFormQuery(form);
      }

      function collectSearchForms() {
        const roleForms = Array.from(document.querySelectorAll('form[role="search"]'));
        const actionForms = Array.from(document.querySelectorAll('form[action]')).filter(isSearchForm);
        return Array.from(new Set(roleForms.concat(actionForms))).filter((form) => !isExcluded(form));
      }

      function collectSearchButtons(searchForms) {
        const selectors = [
          'header details-modal summary[aria-label*="Search" i]',
          'sticky-header details-modal summary[aria-label*="Search" i]',
          'details-modal.header__search summary',
          'details-modal summary[aria-label="Search"]',
          'details-modal summary[aria-label*="Search" i]',
          'summary[aria-label="Search"]',
          'summary[aria-label*="Search" i]',
          'summary[role="button"][aria-label*="Search" i]',
          '.header__icon--search',
          '.header_icon--search',
          '.header__search-toggle',
          '.site-header__search-toggle',
          '.search-toggle',
          '.modal__toggle[aria-label*="Search" i]',
          '.modal_toggle[aria-label*="Search" i]',
          '[data-search-toggle]',
          'button[aria-label="Search"]',
          'button[aria-label*="Search" i]',
          'a[aria-label*="Search" i]',
          'button[title*="Search" i]',
          'a[title*="Search" i]',
          'a[href="/search"]',
          'a[href^="/search?"]',
          '[role="button"][aria-label*="Search" i]'
        ];

        let nodes = [];
        for (const sel of selectors) {
          nodes = nodes.concat(Array.from(document.querySelectorAll(sel)));
        }

        const forms = searchForms || collectSearchForms();
        for (const form of forms) {
          nodes = nodes.concat(
            Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"], input[type="image"]'))
          );
        }

        return Array.from(new Set(nodes)).filter((el) => {
          if (isExcluded(el) || !isVisible(el)) return false;

          const rect = el.getBoundingClientRect();
          const tag = el.tagName.toLowerCase();
          const descriptor = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${el.id || ''} ${el.className || ''}`.toLowerCase();
          const parentForm = el.closest('form');

          if (rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
          if (isSearchForm(parentForm)) return true;

          if (tag === 'a') {
            const href = el.getAttribute('href') || el.href || '';
            if (isSearchPath(href)) return true;
          }

          if (
            el.matches('[data-search-toggle], .header__icon--search, .header_icon--search, .header__search-toggle, .site-header__search-toggle, .search-toggle, .modal__toggle[aria-label*="Search" i], .modal_toggle[aria-label*="Search" i], details-modal summary[aria-label*="Search" i]')
          ) {
            return true;
          }

          return /\bsearch\b/.test(descriptor);
        });
      }

      function collectSearchInputs(searchForms) {
        const selectors = [
          'input[type="search"]',
          'input[name="q"]',
          'input[placeholder*="Search" i]',
          'input[id*="search" i]'
        ];
        let inputs = [];
        for (const sel of selectors) inputs = inputs.concat(Array.from(document.querySelectorAll(sel)));

        const forms = searchForms || collectSearchForms();
        for (const form of forms) {
          inputs = inputs.concat(
            Array.from(
              form.querySelectorAll('input[name="q"], input[type="search"], input[placeholder*="Search" i], input[id*="search" i]')
            )
          );
        }

        return Array.from(new Set(inputs)).filter((input) => {
          if (isExcluded(input) || !isVisible(input)) return false;
          const parentForm = input.closest('form');
          if (isSearchForm(parentForm)) return true;
          const descriptor = `${input.id || ''} ${input.className || ''} ${input.getAttribute('placeholder') || ''}`.toLowerCase();
          return /\bsearch\b/.test(descriptor);
        });
      }

      function findPrimarySearchButton(candidates) {
        if (!candidates.length) return null;

        const ranked = candidates
          .map((n) => {
            const r = n.getBoundingClientRect();
            const inHeader = !!n.closest('header, sticky-header, .header-wrapper, .shopify-section-group-header-group');
            const inDetailsModal = !!n.closest('details-modal');
            const isSummary = n.tagName && n.tagName.toLowerCase() === 'summary';
            const isDesktopVisible = !n.classList.contains('medium-hide') && !n.classList.contains('large-up-hide');
            const score =
              (inHeader ? 100 : 0) +
              (inDetailsModal ? 80 : 0) +
              (isSummary ? 40 : 0) +
              (isDesktopVisible ? 20 : 0) +
              (r.top < 180 ? 20 : 0) +
              (r.left > window.innerWidth / 2 ? 15 : 0);

            return { n, r, score };
          })
          .filter(({ r }) => r.width > 0 && r.height > 0)
          .sort((a, b) => {
            if (b.score !== a.score) return b.score - a.score;
            return (a.r.top - b.r.top) || (b.r.left - a.r.left);
          });

        return ranked[0] ? ranked[0].n : null;
      }


      function positionPanelBelow(rect) {
        const gap = 8;
        const panelWidth = panel.offsetWidth || 350;

        let left = rect.right - panelWidth;
        left = Math.max(8, Math.min(left, window.innerWidth - panelWidth - 8));

        let top = rect.bottom + gap;
        const panelHeight = panel.offsetHeight || 420;
        if (top + panelHeight > window.innerHeight - 8) {
          top = Math.max(8, rect.top - gap - panelHeight);
        }

        panel.style.left = left + 'px';
        panel.style.top = top + 'px';
      }

      function openFromRect(rect, seedQuery) {
        lastOpenTs = Date.now();
        if (typeof seedQuery === 'string' && seedQuery.length) searchInput.value = seedQuery;
        positionPanelBelow(rect);
        container.classList.remove('semantic-search-minimized');
        setTimeout(() => searchInput.focus(), 0);
      }

      function openFromElement(el, seedQuery) {
        const anchor = el && el.getBoundingClientRect ? el : overlayBtn;
        openFromRect(anchor.getBoundingClientRect(), seedQuery);
      }

      function interceptAndOpen(e, anchorEl, seedQuery) {
        if (!anchorEl || isExcluded(anchorEl)) return;
        if (typeof e.preventDefault === 'function') e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
        openFromElement(anchorEl, seedQuery || readQueryFromElement(anchorEl));
      }

      function onSearchTriggerClick(e) {
        interceptAndOpen(e, e.currentTarget);
      }

      function onSearchTriggerPointerDown(e) {
        interceptAndOpen(e, e.currentTarget);
      }

      function onSearchTriggerKeydown(e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        interceptAndOpen(e, e.currentTarget);
      }

      function onSearchFormSubmit(e) {
        const form = e.currentTarget;
        const anchor =
          form.querySelector('button[type="submit"], input[type="submit"], input[type="image"]') ||
          form.querySelector('input[name="q"], input[type="search"]') ||
          form;
        interceptAndOpen(e, anchor, readFormQuery(form));
      }

      function onSearchInputPointerDown(e) {
        interceptAndOpen(e, e.currentTarget);
      }

      function onSearchInputFocus(e) {
        const input = e.currentTarget;
        if (!container.classList.contains('semantic-search-minimized')) return;
        openFromElement(input, readQueryFromElement(input));
      }

      function onSearchInputKeydown(e) {
        if (e.key !== 'Enter') return;
        interceptAndOpen(e, e.currentTarget);
      }

      function bindNativeSearchInterceptors() {
        const forms = collectSearchForms();
        const buttons = collectSearchButtons(forms);
        const inputs = collectSearchInputs(forms);

        for (const form of forms) {
          if (boundForms.has(form)) continue;
          boundForms.add(form);
          form.addEventListener('submit', onSearchFormSubmit, true);
        }

        for (const btn of buttons) {
          if (boundTriggerEls.has(btn)) continue;
          boundTriggerEls.add(btn);
          btn.addEventListener('pointerdown', onSearchTriggerPointerDown, true);
          btn.addEventListener('click', onSearchTriggerClick, true);
          btn.addEventListener('keydown', onSearchTriggerKeydown, true);
        }

        for (const input of inputs) {
          if (boundInputEls.has(input)) continue;
          boundInputEls.add(input);
          input.addEventListener('pointerdown', onSearchInputPointerDown, true);
          input.addEventListener('focus', onSearchInputFocus, true);
          input.addEventListener('keydown', onSearchInputKeydown, true);
        }

        return { forms, buttons, inputs };
      }

      function isNativeSearchTarget(target) {
        if (!target || !target.closest) return false;
        if (panel.contains(target) || overlayBtn.contains(target) || fallbackBtn.contains(target)) return false;

        const directSearchControl = target.closest(
          [
            'summary[aria-label*="Search" i]',
            '[data-search-toggle]',
            '.header__icon--search',
            '.header_icon--search',
            '.header__search-toggle',
            '.site-header__search-toggle',
            '.search-toggle',
            '.modal__toggle[aria-label*="Search" i]',
            '.modal_toggle[aria-label*="Search" i]',
            'button[aria-label*="Search" i]',
            'a[aria-label*="Search" i]',
            'button[title*="Search" i]',
            'a[title*="Search" i]',
            'input[name="q"]',
            'input[type="search"]'
          ].join(', ')
        );
        if (directSearchControl) return true;

        const form = target.closest('form');
        if (isSearchForm(form)) return true;

        const link = target.closest('a[href]');
        if (link) {
          const href = link.getAttribute('href') || link.href || '';
          if (isSearchPath(href)) return true;
        }

        return false;
      }

      function openOverlayPanel(e) {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
          if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
        }
        suppressAutoUpdateUntil = Date.now() + 300;
        openFromRect(overlayBtn.getBoundingClientRect());
      }

      overlayBtn.addEventListener('pointerdown', openOverlayPanel, true);
      overlayBtn.addEventListener('mousedown', openOverlayPanel, true);
      overlayBtn.addEventListener('click', openOverlayPanel, true);

      fallbackBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const rect = fallbackBtn.getBoundingClientRect();
        openFromRect(rect);
      });

      document.addEventListener('click', (e) => {
        if (container.classList.contains('semantic-search-minimized')) return;
        if (panel.contains(e.target)) return;
        if (e.target === overlayBtn || overlayBtn.contains(e.target)) return;
        if (e.target === fallbackBtn || fallbackBtn.contains(e.target)) return;
        if (Date.now() - lastOpenTs < OPEN_CLOSE_GUARD_MS) return;
        if (isNativeSearchTarget(e.target)) return;
        container.classList.add('semantic-search-minimized');
      });

      function update() {
        lockFloatingStyles(overlayBtn);
        lockFloatingStyles(fallbackBtn);

        const bindings = bindNativeSearchInterceptors();
        const candidateBtn = findPrimarySearchButton(bindings.buttons);
        const now = Date.now();

        if (!container.classList.contains('semantic-search-minimized') && now < suppressAutoUpdateUntil) {
          if (lastNativeRect) positionPanelBelow(lastNativeRect);
          return;
        }

        if (candidateBtn !== pendingNativeBtn) {
          pendingNativeBtn = candidateBtn;
          pendingNativeSince = now;
        }

        const nativeBtn =
          pendingNativeBtn && now - pendingNativeSince >= ANCHOR_STABILITY_MS
            ? pendingNativeBtn
            : currentNativeBtn || pendingNativeBtn;

        currentNativeBtn = nativeBtn;

        if (nativeBtn && isVisible(nativeBtn)) {
          lastNativeSeenTs = now;
          lastNativeRect = nativeBtn.getBoundingClientRect();
        }

        const shouldHoldNativeAnchor =
          !nativeBtn && !!lastNativeRect && now - lastNativeSeenTs < NATIVE_STABILITY_MS;
        const hasSearchSurface =
          bindings.forms.length > 0 || bindings.inputs.length > 0 || bindings.buttons.length > 0;

        if (!nativeBtn && !shouldHoldNativeAnchor) {
          setDisplay(overlayBtn, 'none');
          setDisplay(fallbackBtn, hasSearchSurface ? 'none' : 'inline-flex');

          if (!container.classList.contains('semantic-search-minimized')) {
            const anchorEl = bindings.inputs[0] || bindings.buttons[0] || bindings.forms[0] || fallbackBtn;
            positionPanelBelow(anchorEl.getBoundingClientRect());
          }
          return;
        }

        setDisplay(fallbackBtn, 'none');
        setDisplay(overlayBtn, 'inline-flex');

        overlayBtn.className = nativeBtn ? (nativeBtn.className || '') : '';
        overlayBtn.innerHTML = '';
        overlayBtn.textContent = '';

        if (nativeBtn && nativeBtn.tagName.toLowerCase() === 'input') {
          overlayBtn.textContent = nativeBtn.value || nativeBtn.getAttribute('aria-label') || 'Search';
        } else if (nativeBtn) {
          const iconLike = nativeBtn.querySelector('svg, .icon, .icon-search, .svg-wrapper');
          if (iconLike) {
            overlayBtn.appendChild(iconLike.cloneNode(true));
          } else {
            overlayBtn.textContent = nativeBtn.getAttribute('aria-label') || nativeBtn.getAttribute('title') || 'Search';
          }
        } else {
          overlayBtn.textContent = '🔍';
        }

        overlayBtn.setAttribute(
          'aria-label',
          nativeBtn
            ? nativeBtn.getAttribute('aria-label') || nativeBtn.getAttribute('title') || 'Search'
            : 'Search'
        );
        overlayBtn.style.setProperty('pointer-events', 'auto', 'important');

        const rect = container.classList.contains('semantic-search-minimized') ? (nativeBtn ? nativeBtn.getBoundingClientRect() : lastNativeRect) : overlayBtn.getBoundingClientRect();

        if (!rect) return;

        overlayBtn.style.setProperty('top', rect.top + 'px', 'important');
        overlayBtn.style.setProperty('left', rect.left + 'px', 'important');
        overlayBtn.style.setProperty('width', rect.width + 'px', 'important');
        overlayBtn.style.setProperty('height', rect.height + 'px', 'important');

        if (!container.classList.contains('semantic-search-minimized')) {
          positionPanelBelow(rect);
        }
      }

      update();

      window.addEventListener('resize', scheduleUpdate);
      window.addEventListener('scroll', scheduleUpdate, true);

      const mo = new MutationObserver(scheduleUpdate);
      mo.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true
      });
    }

    // -----------------------------
    // Theme detection (existing)
    // -----------------------------
    function enhanceThemeDetection(container) {
      const computedStyle = getComputedStyle(document.documentElement);
      const bodyStyle = getComputedStyle(document.body);

      if (!container.dataset.themePrimary || container.dataset.themePrimary === '#667eea') {
        const primaryColor =
          computedStyle.getPropertyValue('--color-primary').trim() ||
          computedStyle.getPropertyValue('--primary-color').trim() ||
          computedStyle.getPropertyValue('--accent-color').trim() ||
          extractColorFromElement('a') ||
          extractColorFromElement('button') ||
          container.dataset.themePrimary;

        if (primaryColor) container.style.setProperty('--theme-primary', primaryColor);
      }

      if (!container.dataset.themeText) {
        const textColor =
          computedStyle.getPropertyValue('--color-text').trim() ||
          bodyStyle.color ||
          container.dataset.themeText;

        if (textColor) container.style.setProperty('--theme-text', textColor);
      }

      if (!container.dataset.themeBg) {
        const bgColor =
          computedStyle.getPropertyValue('--color-background').trim() ||
          bodyStyle.backgroundColor ||
          container.dataset.themeBg;

        if (bgColor) container.style.setProperty('--theme-bg', bgColor);
      }

      const headingEl = document.querySelector('h1, h2, h3');
      const headingFont =
        computedStyle.getPropertyValue('--font-heading').trim() ||
        (headingEl ? getComputedStyle(headingEl).fontFamily : '') ||
        container.dataset.fontHeading;

      const bodyFont =
        computedStyle.getPropertyValue('--font-body').trim() ||
        bodyStyle.fontFamily ||
        container.dataset.fontBody;

      if (headingFont) container.style.setProperty('--font-heading', headingFont);
      if (bodyFont) container.style.setProperty('--font-body', bodyFont);
    }

    function extractColorFromElement(selector) {
      const element = document.querySelector(selector);
      if (!element) return null;
      const style = getComputedStyle(element);
      return style.backgroundColor !== 'rgba(0, 0, 0, 0)' ? style.backgroundColor : style.color;
    }

    // -----------------------------
    // Results page injection (existing)
    // -----------------------------
    function checkSearchPageIntercept() {
      if (window.location.pathname !== '/search') return;

      const raw = sessionStorage.getItem('wakubo_results');
      if (!raw) return;

      let products;
      try {
        products = JSON.parse(raw);
      } catch (e) {
        return;
      }

      if (!products || !products.length) return;

      const NATIVE_GRIDS = [
        '#product-grid',
        '.search-results-grid',
        '#SearchResultsProductGrid',
        '.main-search__results',
        '[data-id="SearchResultsProducts"]',
        '.collection-grid',
        '#Collection',
        '.product-grid',
        '.search__results'
      ];

      for (const sel of NATIVE_GRIDS) {
        const el = document.querySelector(sel);
        if (el) el.style.display = 'none';
      }

      if (!document.querySelector('.wakubo-results-page')) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
          <p class="wakubo-results-heading">Search Results (${products.length})</p>
          <div class="wakubo-results-page">
            ${products
              .map(
                (p) => `
              <div class="product-result">
                ${p.image_url ? `<img src="${p.image_url}" alt="${escapeHtml(p.title)}" loading="lazy">` : ''}
                <h4>${escapeHtml(p.title)}</h4>
                <p>${escapeHtml((p.description || '').substring(0, 100))}${(p.description || '').length > 100 ? '...' : ''}</p>
                <a href="${p.product_url || '/products/' + p.handle}">View Product →</a>
              </div>
            `
              )
              .join('')}
          </div>
        `;

        const anchor = document.querySelector('main, #MainContent, .main-content, [role="main"]');
        if (anchor) anchor.appendChild(wrapper);
      }
    }

    function escapeHtml(str) {
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    // -----------------------------
    // Search logic (kept same)
    // -----------------------------
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

        if (data.products && data.products.length > 0) {
          sessionStorage.removeItem('wakubo_results');
          sessionStorage.removeItem('wakubo_query');

          sessionStorage.setItem('wakubo_results', JSON.stringify(data.products));
          sessionStorage.setItem('wakubo_query', query);
          sessionStorage.setItem('wakubo_panel_open', '1');
          window.location.href = '/search?q=' + encodeURIComponent(query) + '&wakubo=1';
        } else {
          resultsContainer.innerHTML =
            '<div class="search-empty">No products found. Try a different query.</div>';
        }
      } catch (error) {
        resultsContainer.innerHTML =
          '<div class="search-error">Search failed. Check backend connection.</div>';
        console.error('Search error', error);
      }
    }

    async function handleImageSearch(e) {
      const file = e.target.files && e.target.files[0];
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
          sessionStorage.removeItem('wakubo_results');
          sessionStorage.removeItem('wakubo_query');

          sessionStorage.setItem('wakubo_results', JSON.stringify(data.products));
          sessionStorage.setItem('wakubo_query', 'image-search');
          sessionStorage.setItem('wakubo_panel_open', '1');
          window.location.href = '/search?q=image-search&wakubo=1';
        } else {
          resultsContainer.innerHTML =
            '<div class="search-empty">No matching products found for this image.</div>';
        }
      } catch (error) {
        resultsContainer.innerHTML = '<div class="search-error">Image search failed.</div>';
        console.error('Image search error', error);
      }
    }
  }
})();
