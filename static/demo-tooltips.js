(function () {
    if (!document.querySelector('.demo-banner')) return;
    if (!window.matchMedia('(hover: hover)').matches) return;

    var dimmable = ['.form-group', '.record-card'];

    var spotlight = [
        '.record-card.reviewed',
        '.form-group:has(.field-readonly)',
        '.form-group:has(.field-description)',
        '.confirmation-box',
    ];

    setTimeout(function () {
        var lit = new Set();
        spotlight.forEach(function (sel) {
            var el = document.querySelector(sel);
            if (el) lit.add(el);
        });
        if (!lit.size) return;
        dimmable.forEach(function (sel) {
            document.querySelectorAll(sel).forEach(function (el) {
                if (!lit.has(el)) el.classList.add('demo-dimmed');
            });
        });
    }, 80);
})();
