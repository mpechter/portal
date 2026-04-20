(function () {
    if (!document.querySelector('.demo-banner')) return;

    var FEATURES = [
        {
            selector: '.form-group:has(.field-readonly)',
            title: 'Read-only Field',
            body: 'Parents can see this but can\'t edit it. Admins control which fields are locked.',
            color: '#868e96',
        },
        {
            selector: '.form-group:has(input:not([type="hidden"]):not([type="checkbox"])), .form-group:has(textarea), .form-group:has(select)',
            title: 'Editable Field',
            body: 'Parents can update this directly from their portal.',
            color: '#1971c2',
        },
        {
            selector: '.field-translation',
            title: 'Bilingual Label',
            body: 'Field names can be shown in any language. Configured per field by the admin.',
            color: '#0f766e',
        },
        {
            selector: '.field-description',
            title: 'Help Text',
            body: 'Admins can add a short note under any field to guide parents on what to enter.',
            color: '#b45309',
        },
        {
            selector: '.confirmation-box',
            title: 'Data Confirmation',
            body: 'Parents check this to confirm they\'ve reviewed the record. Admins can track who has and hasn\'t confirmed.',
            color: '#2b8a3e',
        },
        {
            selector: '.review-badge',
            title: 'Confirmed Badge',
            body: 'Appears on a record card once the parent has confirmed it.',
            color: '#2b8a3e',
        },
        {
            selector: '.all-reviewed-banner',
            title: 'All Confirmed',
            body: 'Shown when every linked record has been confirmed by the parent.',
            color: '#2b8a3e',
        },
    ];

    FEATURES.forEach(function (f) {
        document.querySelectorAll(f.selector).forEach(function (el) {
            if (el.closest('[data-demo-color]')) return;
            el.dataset.demoTitle = f.title;
            el.dataset.demoBody  = f.body;
            el.dataset.demoColor = f.color;
        });
    });

    // Label element anchored near the highlighted element
    var label = document.createElement('div');
    label.className = 'demo-hl-label';
    label.innerHTML = '<div class="demo-hl-title"></div><div class="demo-hl-body"></div>';
    document.body.appendChild(label);

    var active = null;
    var raf   = null;

    function positionLabel() {
        if (!active) return;
        var r    = active.getBoundingClientRect();
        var left = r.right + 12;
        if (left + 252 > window.innerWidth - 8) left = r.left - 264;
        var top  = r.top;
        if (top + (label.offsetHeight || 52) > window.innerHeight - 8)
            top = window.innerHeight - (label.offsetHeight || 52) - 8;
        label.style.left = left + 'px';
        label.style.top  = top  + 'px';
        raf = requestAnimationFrame(positionLabel);
    }

    function activate(el) {
        if (el === active) return;
        deactivate();
        active = el;
        var color = el.dataset.demoColor;
        el.style.outline       = '3px solid ' + color;
        el.style.outlineOffset = '3px';
        el.style.borderRadius  = '4px';
        label.querySelector('.demo-hl-title').textContent = el.dataset.demoTitle;
        label.querySelector('.demo-hl-body').textContent  = el.dataset.demoBody;
        label.style.background = color;
        label.classList.add('visible');
        positionLabel();
    }

    var fadingEl  = null;
    var fadeTimer = null;

    function deactivate() {
        cancelAnimationFrame(raf);
        active = null;
        label.classList.remove('visible');
        // clear outline after the fade finishes
        var el = fadingEl;
        setTimeout(function () {
            if (el) {
                el.style.outline       = '';
                el.style.outlineOffset = '';
                el.style.borderRadius  = '';
            }
            fadingEl = null;
        }, 350);
    }

    var leaveTimer = null;

    document.addEventListener('mouseover', function (e) {
        var el = e.target.closest('[data-demo-color]');
        clearTimeout(leaveTimer);
        if (el) activate(el);
    });

    document.addEventListener('mouseout', function (e) {
        if (!e.target.closest('[data-demo-color]')) return;
        fadingEl = active;
        leaveTimer = setTimeout(deactivate, 700);
    });
})();
