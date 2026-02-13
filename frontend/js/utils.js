/**
 * Utility functions for FluTracker.
 */

const Utils = {
    /**
     * Format a number with commas.
     */
    formatNumber(n) {
        if (n == null) return '—';
        return n.toLocaleString('en-US');
    },

    /**
     * Format a percentage with sign.
     */
    formatTrend(pct) {
        if (pct == null) return '—';
        const sign = pct > 0 ? '+' : '';
        return `${sign}${pct.toFixed(1)}%`;
    },

    /**
     * Get CSS class for trend direction.
     */
    trendClass(pct) {
        if (pct == null || Math.abs(pct) < 1) return 'trend-flat';
        return pct > 0 ? 'trend-up' : 'trend-down';
    },

    /**
     * Get trend arrow character.
     */
    trendArrow(pct) {
        if (pct == null || Math.abs(pct) < 1) return '→';
        return pct > 0 ? '↑' : '↓';
    },

    /**
     * Get color for severity level.
     */
    severityColor(level) {
        const colors = {
            low: '#00c853',
            moderate: '#ffd700',
            high: '#ff8c00',
            very_high: '#ff4444',
            critical: '#ff0040',
        };
        return colors[level] || '#5f6368';
    },

    /**
     * Get color for severity score (0-100).
     */
    severityScoreColor(score) {
        if (score >= 80) return '#ff0040';
        if (score >= 60) return '#ff4444';
        if (score >= 40) return '#ff8c00';
        if (score >= 20) return '#ffd700';
        return '#00c853';
    },

    /**
     * Choropleth color scale for cases per 100k population.
     * Calibrated for WHO FluNet lab-confirmed specimen counts:
     * most countries 0-5, high-activity countries 5-40+.
     */
    choroplethColor(value) {
        if (value == null || value === 0) return '#1a1f2e';

        const stops = [
            [0,   '#1a1f2e'],
            [0.1, '#0d3b66'],
            [0.5, '#1565c0'],
            [1,   '#00897b'],
            [3,   '#ffd700'],
            [10,  '#ff8c00'],
            [20,  '#ff4444'],
            [40,  '#ff0040'],
        ];

        for (let i = stops.length - 1; i >= 0; i--) {
            if (value >= stops[i][0]) return stops[i][1];
        }
        return stops[0][1];
    },

    /**
     * Debounce a function.
     */
    debounce(fn, delay = 300) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    },

    /**
     * Format a date string.
     */
    formatDate(dateStr) {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    },

    /**
     * Format relative time.
     */
    timeAgo(dateStr) {
        const now = new Date();
        const then = new Date(dateStr);
        const diff = now - then;
        const hours = Math.floor(diff / 3600000);
        if (hours < 1) return 'just now';
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    },

    /**
     * Color palette for comparison lines.
     */
    COMPARISON_COLORS: ['#4a9eff', '#00d4aa', '#ff8c00', '#ff4444', '#a855f7'],

    /**
     * Flu type colors.
     */
    FLU_TYPE_COLORS: {
        'H1N1': '#4a9eff',
        'H3N2': '#ff8c00',
        'B/Victoria': '#00d4aa',
        'B/Yamagata': '#a855f7',
        'B (lineage unknown)': '#9aa0a6',
        'A (unsubtyped)': '#ffd700',
        'unknown': '#5f6368',
    },

    /**
     * Get flu type color.
     */
    fluTypeColor(type) {
        return this.FLU_TYPE_COLORS[type] || '#5f6368';
    },
};
