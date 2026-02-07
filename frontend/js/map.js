/**
 * Leaflet map module for FluTracker.
 * Displays choropleth world map with country-level flu data.
 */

const FluMap = {
    map: null,
    geoLayer: null,
    regionLayer: null,
    anomalyLayer: null,
    topoData: null,
    countryData: {},
    selectedCountry: null,
    currentMetric: 'cases',

    async init() {
        // Initialize Leaflet map
        this.map = L.map('map', {
            center: [20, 0],
            zoom: 2,
            minZoom: 2,
            maxZoom: 7,
            zoomControl: true,
            attributionControl: false,
            worldCopyJump: true,
        });

        // Dark tile layer
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(this.map);

        // Label layer on top
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png', {
            subdomains: 'abcd',
            maxZoom: 19,
            pane: 'overlayPane',
        }).addTo(this.map);

        // Load TopoJSON for country boundaries
        try {
            const resp = await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json');
            this.topoData = await resp.json();
        } catch (e) {
            console.error('Failed to load TopoJSON', e);
            return;
        }

        // Initialize layers
        this.anomalyLayer = L.layerGroup().addTo(this.map);
        this.regionLayer = L.layerGroup().addTo(this.map);

        // Map metric selector
        document.getElementById('mapMetric').addEventListener('change', (e) => {
            this.currentMetric = e.target.value;
            this.updateChoropleth();
        });
    },

    /**
     * Update map with new data from API.
     */
    async update(mapData, severityData, anomalies) {
        if (!this.topoData) return;

        // Build lookup from API data
        this.countryData = {};
        if (mapData && mapData.features) {
            mapData.features.forEach(f => {
                this.countryData[f.id] = f.properties;
            });
        }

        // Merge severity data
        if (severityData) {
            severityData.forEach(s => {
                if (this.countryData[s.country_code]) {
                    this.countryData[s.country_code].severity_score = s.score;
                    this.countryData[s.country_code].severity_level = s.level;
                }
            });
        }

        this.updateChoropleth();
        this.updateAnomalyMarkers(anomalies);
        this.updateLegend();
    },

    /**
     * Render/update the choropleth layer.
     */
    updateChoropleth() {
        if (this.geoLayer) {
            this.map.removeLayer(this.geoLayer);
        }

        const geoFeatures = topojson.feature(this.topoData, this.topoData.objects.countries);
        const iso3to2 = this._buildIso3to2Map();

        this.geoLayer = L.geoJSON(geoFeatures, {
            style: (feature) => {
                const code2 = iso3to2[feature.id] || iso3to2[feature.properties?.name];
                const data = code2 ? this.countryData[code2] : null;
                const value = this._getMetricValue(data);

                return {
                    fillColor: Utils.choroplethColor(value, this.currentMetric),
                    fillOpacity: 0.75,
                    weight: 1,
                    color: '#2a3346',
                    opacity: 0.8,
                };
            },
            onEachFeature: (feature, layer) => {
                const code2 = iso3to2[feature.id] || iso3to2[feature.properties?.name];
                const data = code2 ? this.countryData[code2] : null;

                if (data) {
                    layer.bindPopup(this._createPopup(data));

                    layer.on('mouseover', function () {
                        this.setStyle({ weight: 2, color: '#4a9eff' });
                        this.bringToFront();
                    });
                    layer.on('mouseout', function () {
                        this.setStyle({ weight: 1, color: '#2a3346' });
                    });
                    layer.on('click', () => {
                        this.selectCountry(code2, data.country_name);
                    });
                }
            },
        }).addTo(this.map);
    },

    /**
     * Select a country — zoom in and trigger chart/table updates.
     */
    selectCountry(code, name) {
        this.selectedCountry = code;

        // Dispatch custom event for other modules
        window.dispatchEvent(new CustomEvent('countrySelected', {
            detail: { code, name },
        }));
    },

    /**
     * Show region-level bubbles when drilling into a country.
     */
    async showRegions(regionData) {
        this.regionLayer.clearLayers();

        if (!regionData || !regionData.regions) return;

        regionData.regions.forEach(r => {
            if (!r.lat || !r.lon) return;

            const radius = Math.max(5, Math.min(30, Math.sqrt(r.total_cases) * 0.5));
            const circle = L.circleMarker([r.lat, r.lon], {
                radius,
                fillColor: '#4a9eff',
                fillOpacity: 0.6,
                weight: 1,
                color: '#4a9eff',
                opacity: 0.8,
            });

            circle.bindPopup(`
                <div class="popup-country-name">${r.region}</div>
                <div class="popup-stat">
                    <span class="popup-stat-label">Cases:</span>
                    <span class="popup-stat-value">${Utils.formatNumber(r.total_cases)}</span>
                </div>
            `);

            this.regionLayer.addLayer(circle);
        });
    },

    /**
     * Add pulsing markers for anomalies.
     */
    updateAnomalyMarkers(anomalies) {
        this.anomalyLayer.clearLayers();
        if (!anomalies) return;

        // We'd need lat/lon for anomaly locations — use country centroids for now
        const centroids = this._countryCentroids();

        anomalies.forEach(a => {
            const pos = centroids[a.country_code];
            if (!pos) return;

            const icon = L.divIcon({
                className: 'anomaly-marker',
                html: `<div style="
                    width: 16px; height: 16px;
                    background: ${Utils.severityColor(a.severity)};
                    border-radius: 50%;
                    border: 2px solid white;
                    box-shadow: 0 0 8px ${Utils.severityColor(a.severity)};
                "></div>`,
                iconSize: [16, 16],
            });

            L.marker(pos, { icon })
                .bindPopup(`
                    <div class="popup-country-name">${a.description || a.country_code}</div>
                    <div class="popup-stat">
                        <span class="popup-stat-label">Z-score:</span>
                        <span class="popup-stat-value">${a.z_score.toFixed(1)}</span>
                    </div>
                    <div class="popup-stat">
                        <span class="popup-stat-label">Severity:</span>
                        <span class="popup-stat-value" style="color:${Utils.severityColor(a.severity)}">${a.severity}</span>
                    </div>
                `)
                .addTo(this.anomalyLayer);
        });
    },

    /**
     * Update the legend below the map.
     */
    updateLegend() {
        const legend = document.getElementById('mapLegend');
        const labels = this.currentMetric === 'trend'
            ? ['<-20%', '-5%', '0%', '+5%', '>+20%']
            : ['0', '5', '15', '30', '60', '100+'];

        const colors = this.currentMetric === 'trend'
            ? ['#00c853', '#69f0ae', '#ffd700', '#ff8c00', '#ff4444']
            : ['#1a1f2e', '#0d3b66', '#1565c0', '#00897b', '#ffd700', '#ff4444'];

        legend.innerHTML = `
            <span class="legend-label">${labels[0]}</span>
            <div class="legend-bar">
                ${colors.map(c => `<div class="segment" style="background:${c}"></div>`).join('')}
            </div>
            <span class="legend-label">${labels[labels.length - 1]}</span>
        `;
    },

    // --- Private helpers ---

    _getMetricValue(data) {
        if (!data) return 0;
        switch (this.currentMetric) {
            case 'per_100k': return data.cases_per_100k || 0;
            case 'trend': return data.trend_pct || 0;
            case 'severity': return data.severity_score || 0;
            default: return data.new_cases_7d || 0;
        }
    },

    _createPopup(data) {
        return `
            <div class="popup-country-name">${data.country_name}</div>
            <div class="popup-stat">
                <span class="popup-stat-label">Cases (7d):</span>
                <span class="popup-stat-value">${Utils.formatNumber(data.new_cases_7d)}</span>
            </div>
            <div class="popup-stat">
                <span class="popup-stat-label">Per 100k:</span>
                <span class="popup-stat-value">${data.cases_per_100k != null ? data.cases_per_100k.toFixed(1) : '—'}</span>
            </div>
            <div class="popup-stat">
                <span class="popup-stat-label">Trend:</span>
                <span class="popup-stat-value ${Utils.trendClass(data.trend_pct)}">${Utils.trendArrow(data.trend_pct)} ${Utils.formatTrend(data.trend_pct)}</span>
            </div>
            <div class="popup-stat">
                <span class="popup-stat-label">Type:</span>
                <span class="popup-stat-value">${data.dominant_flu_type || '—'}</span>
            </div>
        `;
    },

    _buildIso3to2Map() {
        // Map numeric ISO IDs and ISO3 codes to ISO2
        // world-atlas uses numeric ISO codes
        const numericToAlpha2 = {
            4: 'AF', 8: 'AL', 12: 'DZ', 24: 'AO', 32: 'AR', 36: 'AU',
            40: 'AT', 50: 'BD', 56: 'BE', 204: 'BJ', 68: 'BO', 76: 'BR',
            854: 'BF', 108: 'BI', 116: 'KH', 120: 'CM', 124: 'CA', 148: 'TD',
            152: 'CL', 156: 'CN', 170: 'CO', 180: 'CD', 178: 'CG', 384: 'CI',
            192: 'CU', 203: 'CZ', 208: 'DK', 214: 'DO', 218: 'EC', 818: 'EG',
            222: 'SV', 231: 'ET', 246: 'FI', 250: 'FR', 276: 'DE', 288: 'GH',
            300: 'GR', 320: 'GT', 324: 'GN', 332: 'HT', 340: 'HN', 348: 'HU',
            356: 'IN', 360: 'ID', 364: 'IR', 368: 'IQ', 372: 'IE', 376: 'IL',
            380: 'IT', 392: 'JP', 400: 'JO', 398: 'KZ', 404: 'KE', 408: 'KP',
            410: 'KR', 422: 'LB', 434: 'LY', 450: 'MG', 454: 'MW', 458: 'MY',
            466: 'ML', 484: 'MX', 504: 'MA', 508: 'MZ', 104: 'MM', 524: 'NP',
            528: 'NL', 554: 'NZ', 562: 'NE', 566: 'NG', 578: 'NO', 586: 'PK',
            604: 'PE', 608: 'PH', 616: 'PL', 620: 'PT', 642: 'RO', 643: 'RU',
            646: 'RW', 682: 'SA', 686: 'SN', 688: 'RS', 694: 'SL', 702: 'SG',
            706: 'SO', 710: 'ZA', 728: 'SS', 724: 'ES', 144: 'LK', 729: 'SD',
            752: 'SE', 756: 'CH', 760: 'SY', 158: 'TW', 834: 'TZ', 764: 'TH',
            768: 'TG', 788: 'TN', 792: 'TR', 800: 'UG', 804: 'UA', 784: 'AE',
            826: 'GB', 840: 'US', 860: 'UZ', 862: 'VE', 704: 'VN', 887: 'YE',
            894: 'ZM', 716: 'ZW',
        };
        return numericToAlpha2;
    },

    _countryCentroids() {
        return {
            US: [39.8, -98.5], GB: [54.0, -2.0], IN: [20.6, 78.9],
            BR: [-14.2, -51.9], DE: [51.2, 10.5], FR: [46.2, 2.2],
            JP: [36.2, 138.3], AU: [-25.3, 133.8], CA: [56.1, -106.3],
            KR: [35.9, 127.8], MX: [23.6, -102.6], RU: [61.5, 105.3],
            CN: [35.9, 104.2], ID: [-0.8, 113.9], PK: [30.4, 69.3],
            NG: [9.1, 8.7], BD: [23.7, 90.4], EG: [26.8, 30.8],
            ET: [9.1, 40.5], PH: [12.9, 121.8], VN: [14.1, 108.3],
            TR: [38.9, 35.2], IR: [32.4, 53.7], TH: [15.9, 100.9],
            ZA: [-30.6, 22.9], IT: [41.9, 12.6], ES: [40.5, -3.7],
            CO: [4.6, -74.3], KE: [-0.0, 37.9], UA: [48.4, 31.2],
            PL: [51.9, 19.1], AR: [-38.4, -63.6], DZ: [28.0, 1.7],
            IQ: [33.2, 43.7], SA: [23.9, 45.1], PE: [-9.2, -75.0],
            MA: [31.8, -7.1], MY: [4.2, 101.9], GH: [7.9, -1.0],
        };
    },
};
