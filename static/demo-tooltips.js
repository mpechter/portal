(function () {
    if (!document.querySelector('.demo-banner')) return;

    var annotations = [
        {
            selector: '.form-group:has(.field-readonly)',
            title: 'Read-only Field',
            tip: 'Locked by the administrator — parents can see this value but cannot edit it. Useful for fields like grade level or homeroom that only staff should change.',
            cursor: true,
        },
        {
            selector: '.form-group:has(input:not([type="hidden"]):not([type="checkbox"])), .form-group:has(textarea), .form-group:has(select)',
            title: 'Editable Field',
            tip: 'Parents can update this directly from their portal. Administrators choose which fields are editable on a field-by-field basis.',
            cursor: false,
        },
        {
            selector: '.field-translation',
            title: 'Bilingual Label',
            tip: 'Field names can be shown in any language alongside the original. Administrators configure a translation per field — helpful for multilingual families.',
            cursor: true,
        },
        {
            selector: '.field-description',
            title: 'Help Text',
            tip: 'Administrators can add a short note under any field to guide parents on what to enter or why the information is needed.',
            cursor: true,
        },
        {
            selector: '.confirmation-box',
            title: 'Data Confirmation',
            tip: 'Parents check this box to confirm they\'ve reviewed the record. Administrators can see who has and hasn\'t confirmed — great for annual enrollment or info updates.',
            cursor: true,
        },
        {
            selector: '.review-badge',
            title: 'Confirmation Badge',
            tip: 'Appears on a record card once a parent has confirmed it. Unreviewed records appear without the badge so parents know what still needs attention.',
            cursor: true,
        },
        {
            selector: '.all-reviewed-banner',
            title: 'All Confirmed',
            tip: 'Once a parent has confirmed every linked record, this banner appears as a clear signal that nothing is left to review.',
            cursor: true,
        },
    ];

    annotations.forEach(function (a) {
        document.querySelectorAll(a.selector).forEach(function (el) {
            if (el.closest('[data-demo-tip]')) return;
            el.dataset.demoTitle = a.title;
            el.dataset.demoTip = a.tip;
            if (a.cursor) el.style.cursor = 'help';
        });
    });

    var tooltip = document.createElement('div');
    tooltip.className = 'demo-tooltip';
    tooltip.innerHTML = '<div class="demo-tooltip-title"></div><div class="demo-tooltip-body"></div>';
    document.body.appendChild(tooltip);

    var active = null;
    var hideTimer = null;

    function position(x, y) {
        var w = 268, h = tooltip.offsetHeight || 80;
        var left = x + 18, top = y + 14;
        if (left + w > window.innerWidth - 8) left = x - w - 10;
        if (top + h > window.innerHeight - 8) top = y - h - 10;
        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
    }

    document.addEventListener('mouseover', function (e) {
        var el = e.target.closest('[data-demo-tip]');
        if (!el) {
            clearTimeout(hideTimer);
            hideTimer = setTimeout(function () {
                tooltip.classList.remove('visible');
                active = null;
            }, 80);
            return;
        }
        clearTimeout(hideTimer);
        if (el === active) return;
        active = el;
        tooltip.querySelector('.demo-tooltip-title').textContent = el.dataset.demoTitle || '';
        tooltip.querySelector('.demo-tooltip-body').textContent = el.dataset.demoTip || '';
        position(e.clientX, e.clientY);
        tooltip.classList.add('visible');
    });

    document.addEventListener('mousemove', function (e) {
        if (active) position(e.clientX, e.clientY);
    });
})();
