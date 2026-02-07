/**
 * API client for FluTracker backend.
 */

const API = {
    BASE: '/api',

    async _fetch(path, params = {}) {
        const url = new URL(this.BASE + path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v != null && v !== '') url.searchParams.set(k, v);
        });

        try {
            const response = await fetch(url);
            if (!response.ok) {
                console.error(`API error: ${response.status} ${path}`);
                return null;
            }
            return await response.json();
        } catch (err) {
            console.error(`API fetch failed: ${path}`, err);
            return null;
        }
    },

    async getCountries(continent = null) {
        return this._fetch('/countries', { continent });
    },

    async getSummary() {
        return this._fetch('/summary');
    },

    async getCases(params = {}) {
        return this._fetch('/cases', params);
    },

    async getCasesByRegion(country, days = 7) {
        return this._fetch('/cases/by-region', { country, days });
    },

    async getTrends(country, granularity = 'week', weeks = 12) {
        return this._fetch('/trends', { country, granularity, weeks });
    },

    async getGlobalTrends(granularity = 'week', weeks = 12) {
        return this._fetch('/trends/global', { granularity, weeks });
    },

    async getHistoricalSeasons(country = null, seasons = 5) {
        return this._fetch('/trends/historical-seasons', { country, seasons });
    },

    async compareTrends(countries, granularity = 'week', weeks = 12) {
        return this._fetch('/trends/compare', {
            countries: countries.join(','),
            granularity,
            weeks,
        });
    },

    async getMapGeoJSON(period = 7) {
        return this._fetch('/map/geojson', { period });
    },

    async getFluTypes(country = null, days = 28) {
        return this._fetch('/flu-types', { country, days });
    },

    async getAnomalies(days = 7) {
        return this._fetch('/anomalies', { days });
    },

    async getForecast(country, weeksAhead = 4) {
        return this._fetch('/forecast', { country, weeks_ahead: weeksAhead });
    },

    async getSeverity() {
        return this._fetch('/severity');
    },

    async getHealth() {
        return this._fetch('/health');
    },
};
