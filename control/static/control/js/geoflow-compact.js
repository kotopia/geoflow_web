/* Reuse AdminKit's compact/default modes and Bootstrap collapse controls. */
document.addEventListener('DOMContentLoaded', function () {
  var sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  var narrow = window.matchMedia('(max-width: 991.98px)');
  function applyLayout() {

    sidebar.querySelectorAll('.sidebar-nav > .sidebar-item > .sidebar-dropdown').forEach(function (menu) {
      var parentLink = menu.parentElement.querySelector('.sidebar-link');
      var first = menu.querySelector('a[href]');
      if (parentLink && first) {
        parentLink.href = first.href;
        if (narrow.matches) parentLink.setAttribute('data-bs-toggle', 'collapse');
        else parentLink.removeAttribute('data-bs-toggle');
      }
      var active = !!menu.querySelector('[aria-current="page"]');
      menu.classList.toggle('show', narrow.matches && active);
      var trigger = menu.parentElement.querySelector('[data-bs-toggle="collapse"]');
      if (trigger) {
        trigger.classList.toggle('collapsed', !(narrow.matches && active));
        trigger.setAttribute('aria-expanded', String(narrow.matches && active));
      }
    });
  }
  // Initial layout is applied before sidebar markup; only menu interaction waits for DOM readiness.
  applyLayout();
  narrow.addEventListener('change', applyLayout);
  sidebar.querySelectorAll('.sidebar-nav > .sidebar-item > .sidebar-link').forEach(function (link) {
    var label = link.textContent.trim();
    link.setAttribute('aria-label', label);
    link.setAttribute('title', label);
    link.addEventListener('click', function (event) {
      if (!narrow.matches || !event.target.closest('svg, i')) return;
      var first = link.parentElement.querySelector('.sidebar-dropdown a[href]');
      if (!first) return;
      event.preventDefault(); event.stopPropagation();
      window.location.assign(first.href);
    });
  });
  sidebar.querySelectorAll('.sidebar-dropdown a[href]').forEach(function (link) {
    if (link.pathname !== window.location.pathname) return;
    link.setAttribute('aria-current', 'page');
    link.parentElement.classList.add('active');
    var menu = link.closest('.sidebar-dropdown');
    if (narrow.matches) menu.classList.add('show');
    var trigger = menu.parentElement.querySelector('[data-bs-toggle="collapse"]');
    if (trigger && narrow.matches) {
      trigger.classList.remove('collapsed');
      trigger.setAttribute('aria-expanded', 'true');
    }
  });
});
