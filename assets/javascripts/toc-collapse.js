// Collapsible TOC for settings page
(function() {
  function initCollapsibleTOC() {
    // Only apply to pages with many TOC items (like settings)
    var tocNav = document.querySelector('.md-nav--secondary');
    if (!tocNav) return;

    // Skip if already initialized
    if (tocNav.dataset.tocCollapse === 'true') return;
    tocNav.dataset.tocCollapse = 'true';

    var tocItems = tocNav.querySelectorAll('.md-nav__item');
    if (tocItems.length < 20) return;

    // Find all top-level TOC items that have nested lists
    var topList = tocNav.querySelector('.md-nav__list');
    if (!topList) return;

    var sections = topList.children;

    for (var i = 0; i < sections.length; i++) {
      (function(section) {
        var nestedNav = section.querySelector('.md-nav');
        if (!nestedNav) return;

        var link = section.querySelector('.md-nav__link');
        if (!link) return;

        // Skip if already has toggle
        if (link.querySelector('.toc-toggle')) return;

        // Collapse by default
        nestedNav.style.display = 'none';

        // Create toggle button
        var toggle = document.createElement('span');
        toggle.className = 'toc-toggle';
        toggle.innerHTML = '+';
        toggle.style.float = 'right';
        toggle.style.marginRight = '0.5rem';
        toggle.style.fontWeight = 'bold';
        toggle.style.cursor = 'pointer';
        toggle.style.userSelect = 'none';
        link.appendChild(toggle);

        // Toggle function for this specific section
        function toggleSection(e) {
          if (e) {
            e.preventDefault();
            e.stopPropagation();
          }

          if (nestedNav.style.display === 'none') {
            nestedNav.style.display = 'block';
            toggle.innerHTML = '−';
          } else {
            nestedNav.style.display = 'none';
            toggle.innerHTML = '+';
          }
        }

        // Click on toggle button
        toggle.onclick = toggleSection;
      })(sections[i]);
    }
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCollapsibleTOC);
  } else {
    initCollapsibleTOC();
  }

  // Re-run on instant navigation (MkDocs Material)
  if (typeof document$ !== 'undefined') {
    document$.subscribe(initCollapsibleTOC);
  }
})();
