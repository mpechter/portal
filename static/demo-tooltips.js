(function () {
    if (!document.querySelector('.demo-banner')) return;
    if (!window.matchMedia('(hover: hover)').matches) return;

    var color = getComputedStyle(document.documentElement)
                    .getPropertyValue('--color-primary').trim() || '#007bff';

    var FEATURES = [
        { selector: '.form-group:has(.field-readonly)', title: 'Read-only Field' },
        {
            selector: '.form-group:has(input:not([type="hidden"]):not([type="checkbox"])), .form-group:has(textarea), .form-group:has(select)',
            title: 'Editable Field',
        },
        { selector: '.field-translation',    title: 'Bilingual Label'    },
        { selector: '.field-description',    title: 'Help Text'          },
        { selector: '.confirmation-box',     title: 'Data Confirmation'  },
        { selector: '.review-badge',         title: 'Confirmed Badge'    },
        { selector: '.all-reviewed-banner',  title: 'All Confirmed'      },
    ];

    FEATURES.forEach(function (f) {
        document.querySelectorAll(f.selector).forEach(function (el) {
            if (el.closest('[data-demo-title]')) return;
            el.dataset.demoTitle = f.title;
        });
    });

    var label = document.createElement('div');
    label.className = 'demo-hl-label';
    label.style.background = color;
    document.body.appendChild(label);

    var active = null;
    var raf    = null;

    function positionLabel() {
        if (!active) return;
        var r    = active.getBoundingClientRect();
        var left = r.right + 12;
        if (left + 210 > window.innerWidth - 8) left = r.left - 222;
        var top  = r.top;
        if (top + label.offsetHeight > window.innerHeight - 8)
            top = window.innerHeight - label.offsetHeight - 8;
        label.style.left = left + 'px';
        label.style.top  = top  + 'px';
        raf = requestAnimationFrame(positionLabel);
    }

    function activate(el) {
        if (el === active) return;
        deactivate();
        active = el;
        el.style.outline       = '3px solid ' + color;
        el.style.outlineOffset = '3px';
        el.style.borderRadius  = '4px';
        label.textContent = el.dataset.demoTitle;
        label.classList.add('visible');
        positionLabel();
    }

    function deactivate() {
        cancelAnimationFrame(raf);
        if (active) {
            active.style.outline       = '';
            active.style.outlineOffset = '';
            active.style.borderRadius  = '';
            active = null;
        }
        label.classList.remove('visible');
    }

    document.addEventListener('mouseover', function (e) {
        var el = e.target.closest('[data-demo-title]');
        if (el) activate(el);
        else deactivate();
    });
})();
