/**
 * Anomaly alerts module for FluTracker.
 * Manages the anomaly alert bar and notifications.
 */

const Anomalies = {
    alertBar: null,
    alertScroll: null,
    anomalies: [],

    init() {
        this.alertBar = document.getElementById('alertBar');
        this.alertScroll = document.getElementById('alertScroll');
    },

    /**
     * Update the anomaly alert bar with new data.
     */
    update(anomalies) {
        this.anomalies = anomalies || [];

        if (this.anomalies.length === 0) {
            this.alertBar.style.display = 'none';
            return;
        }

        this.alertBar.style.display = 'flex';
        this.alertScroll.innerHTML = '';

        // Sort by z-score descending
        const sorted = [...this.anomalies].sort((a, b) => Math.abs(b.z_score) - Math.abs(a.z_score));

        sorted.forEach(anomaly => {
            const chip = document.createElement('div');
            chip.className = 'alert-chip';
            chip.innerHTML = `
                <span class="severity-dot ${anomaly.severity}"></span>
                ${anomaly.description || anomaly.country_code}
            `;

            chip.addEventListener('click', () => {
                // Navigate to the country on the map and charts
                FluMap.selectCountry(anomaly.country_code, anomaly.country_code);
            });

            this.alertScroll.appendChild(chip);
        });
    },

    /**
     * Get count of active anomalies.
     */
    getCount() {
        return this.anomalies.length;
    },

    /**
     * Get anomalies for a specific country.
     */
    getForCountry(countryCode) {
        return this.anomalies.filter(a => a.country_code === countryCode);
    },
};
