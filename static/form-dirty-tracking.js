(function() {
    const form = document.getElementById('edit-form');
    const saveBtn = document.getElementById('save-btn');
    const discardBtn = document.getElementById('discard-btn');
    if (!form || !saveBtn) return;

    function getInputValue(input) {
        if (input.type === 'checkbox') {
            return input.checked ? 'true' : 'false';
        }
        return input.value;
    }

    function setInputValue(input, value) {
        if (input.type === 'checkbox') {
            input.checked = (value === 'true');
        } else {
            input.value = value;
        }
    }

    function checkForChanges() {
        let hasChanges = false;

        // Check regular inputs
        form.querySelectorAll('input[data-original], textarea[data-original], select[data-original]').forEach(input => {
            if (getInputValue(input) !== input.dataset.original) {
                hasChanges = true;
            }
        });

        // Check multi-select groups
        form.querySelectorAll('.multi-select[data-original]').forEach(group => {
            const checked = Array.from(group.querySelectorAll('input:checked'))
                .map(cb => cb.value)
                .sort()
                .join(',');
            const original = group.dataset.original.split(',').filter(v => v).sort().join(',');
            if (checked !== original) {
                hasChanges = true;
            }
        });

        if (hasChanges) {
            saveBtn.disabled = false;
            saveBtn.classList.add('has-changes');
            if (discardBtn) discardBtn.disabled = false;
        } else {
            saveBtn.disabled = true;
            saveBtn.classList.remove('has-changes');
            if (discardBtn) discardBtn.disabled = true;
        }
    }

    function discardChanges() {
        // Reset regular inputs
        form.querySelectorAll('input[data-original], textarea[data-original], select[data-original]').forEach(input => {
            setInputValue(input, input.dataset.original);
        });

        // Reset multi-select groups
        form.querySelectorAll('.multi-select[data-original]').forEach(group => {
            const originalValues = group.dataset.original.split(',').filter(v => v);
            group.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = originalValues.includes(cb.value);
            });
        });

        checkForChanges();
    }

    // Listen for changes on all form elements
    form.querySelectorAll('input, textarea, select').forEach(input => {
        input.addEventListener('input', checkForChanges);
        input.addEventListener('change', checkForChanges);
    });

    if (discardBtn) {
        discardBtn.addEventListener('click', discardChanges);
    }

    // Run on load to handle browser autofill
    checkForChanges();
})();
