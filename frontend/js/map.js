/**
 * Leaflet map module for FluTracker.
 * Displays choropleth world map with country-level flu data.
 * Supports state-level choropleth drill-down for US and BR.
 */

const FluMap = {
    map: null,
    geoLayer: null,
    regionLayer: null,
    stateLayer: null,
    anomalyLayer: null,
    topoData: null,
    countryData: {},
    selectedCountry: null,
    currentMetric: 'per_100k',
    stateTopoCache: {},  // countryCode -> topoJSON data
    countryCentroids: null,

    // State FIPS codes -> state names for US TopoJSON matching
    _usFipsToName: {
        '01': 'Alabama', '02': 'Alaska', '04': 'Arizona', '05': 'Arkansas',
        '06': 'California', '08': 'Colorado', '09': 'Connecticut', '10': 'Delaware',
        '11': 'District of Columbia', '12': 'Florida', '13': 'Georgia', '15': 'Hawaii',
        '16': 'Idaho', '17': 'Illinois', '18': 'Indiana', '19': 'Iowa',
        '20': 'Kansas', '21': 'Kentucky', '22': 'Louisiana', '23': 'Maine',
        '24': 'Maryland', '25': 'Massachusetts', '26': 'Michigan', '27': 'Minnesota',
        '28': 'Mississippi', '29': 'Missouri', '30': 'Montana', '31': 'Nebraska',
        '32': 'Nevada', '33': 'New Hampshire', '34': 'New Jersey', '35': 'New Mexico',
        '36': 'New York', '37': 'North Carolina', '38': 'North Dakota', '39': 'Ohio',
        '40': 'Oklahoma', '41': 'Oregon', '42': 'Pennsylvania', '44': 'Rhode Island',
        '45': 'South Carolina', '46': 'South Dakota', '47': 'Tennessee', '48': 'Texas',
        '49': 'Utah', '50': 'Vermont', '51': 'Virginia', '53': 'Washington',
        '54': 'West Virginia', '55': 'Wisconsin', '56': 'Wyoming',
        '60': 'American Samoa', '66': 'Guam', '69': 'Northern Mariana Islands',
        '72': 'Puerto Rico', '78': 'Virgin Islands',
    },

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
        this.countryCentroids = this._computeCountryCentroids();

        // Map is locked to per_100k metric
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
     * Normalize anomalies to one display marker per country that can be mapped.
     * Picks the highest z-score anomaly for each country.
     */
    getDisplayAnomalies(anomalies) {
        if (!anomalies || anomalies.length === 0) return [];

        const centroids = this.countryCentroids || this._computeCountryCentroids();
        const byCountry = new Map();

        anomalies.forEach(a => {
            if (!a || !a.country_code) return;
            if (!centroids[a.country_code]) return;

            const existing = byCountry.get(a.country_code);
            if (!existing || (a.z_score || 0) > (existing.z_score || 0)) {
                byCountry.set(a.country_code, a);
            }
        });

        return Array.from(byCountry.values()).sort((a, b) => (b.z_score || 0) - (a.z_score || 0));
    },

    /**
     * Render/update the choropleth layer.
     */
    updateChoropleth() {
        if (this.geoLayer) {
            this.map.removeLayer(this.geoLayer);
        }

        const geoFeatures = topojson.feature(this.topoData, this.topoData.objects.countries);
        this._fixAntimeridian(geoFeatures);
        const iso3to2 = this._buildIso3to2Map();

        // Resolve a TopoJSON feature ID (numeric or zero-padded string) to ISO2
        const resolveCode = (feature) => {
            const id = feature.id;
            return iso3to2[id] || iso3to2[parseInt(id, 10)] || iso3to2[feature.properties?.name];
        };

        this.geoLayer = L.geoJSON(geoFeatures, {
            style: (feature) => {
                const code2 = resolveCode(feature);
                const data = code2 ? this.countryData[code2] : null;
                const value = this._getMetricValue(data);

                return {
                    fillColor: Utils.choroplethColor(value),
                    fillOpacity: 0.75,
                    weight: 1,
                    color: '#2a3346',
                    opacity: 0.8,
                };
            },
            onEachFeature: (feature, layer) => {
                const code2 = resolveCode(feature);
                const data = code2 ? this.countryData[code2] : null;
                const countryName = data?.country_name || feature.properties?.name || code2;

                if (data) {
                    layer.bindPopup(this._createPopup(data));
                } else if (code2) {
                    layer.bindPopup(`
                        <div class="popup-country-name">${countryName || code2}</div>
                        <div class="popup-stat">
                            <span class="popup-stat-label">No recent map data</span>
                        </div>
                    `);
                }

                if (code2) {
                    layer.on('mouseover', function () {
                        this.setStyle({ weight: 2, color: '#F5A623' });
                        this.bringToFront();
                    });
                    layer.on('mouseout', function () {
                        this.setStyle({ weight: 1, color: '#2a3346' });
                    });
                    layer.on('click', () => {
                        this.selectCountry(code2, countryName || code2);
                    });
                }
            },
        }).addTo(this.map);
    },

    /**
     * Select a country — zoom in and trigger chart/table updates.
     */
    selectCountry(code, name) {
        // Clicking the selected country again clears selection.
        if (this.selectedCountry === code) {
            this.selectedCountry = null;
            window.dispatchEvent(new CustomEvent('countrySelected', {
                detail: { code: null, name: null, cleared: true },
            }));
            return;
        }

        this.selectedCountry = code;

        // Dispatch custom event for other modules
        window.dispatchEvent(new CustomEvent('countrySelected', {
            detail: { code, name },
        }));
    },

    /**
     * Show region-level bubbles when drilling into a country (fallback for countries without state TopoJSON).
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
                ${r.trend_pct != null ? `
                <div class="popup-stat">
                    <span class="popup-stat-label">Trend:</span>
                    <span class="popup-stat-value ${Utils.trendClass(r.trend_pct)}">${Utils.trendArrow(r.trend_pct)} ${Utils.formatTrend(r.trend_pct)}</span>
                </div>` : ''}
                ${r.population ? `
                <div class="popup-stat">
                    <span class="popup-stat-label">Per 100k:</span>
                    <span class="popup-stat-value">${(r.total_cases / r.population * 100000).toFixed(1)}</span>
                </div>` : ''}
            `);

            this.regionLayer.addLayer(circle);
        });
    },

    /**
     * Show state-level choropleth for countries with state TopoJSON.
     */
    async showStateChoropleth(countryCode, regionData) {
        // Clear previous state/region layers
        this.regionLayer.clearLayers();
        if (this.stateLayer) {
            this.map.removeLayer(this.stateLayer);
            this.stateLayer = null;
        }

        if (!regionData || !regionData.regions || regionData.regions.length === 0) return;

        // Load state TopoJSON
        const topo = await this._loadStateTopoJSON(countryCode);
        if (!topo) {
            // Fallback to circle markers
            this.showRegions(regionData);
            return;
        }

        // Build region lookup by name
        const regionMap = {};
        regionData.regions.forEach(r => {
            regionMap[r.region] = r;
            // Also store lowercase for fuzzy matching
            regionMap[r.region.toLowerCase()] = r;
        });

        // Determine max cases for color scale
        const maxCases = Math.max(...regionData.regions.map(r => r.total_cases), 1);
        const colorScale = d3.scaleSequential(d3.interpolateYlOrRd)
            .domain([0, maxCases]);

        // Resolve feature name based on country
        const getFeatureName = (feature) => {
            if (countryCode === 'US') {
                // us-atlas uses FIPS codes as IDs
                const fips = String(feature.id).padStart(2, '0');
                return this._usFipsToName[fips] || feature.properties?.name;
            }
            // Brazil TopoJSON uses properties.name
            return feature.properties?.name || feature.properties?.NAME_1;
        };

        // Create GeoJSON from TopoJSON
        let geoFeatures;
        if (countryCode === 'US') {
            geoFeatures = topojson.feature(topo, topo.objects.states);
        } else if (countryCode === 'BR') {
            // Brazil TopoJSON object key
            const objKey = Object.keys(topo.objects)[0];
            geoFeatures = topojson.feature(topo, topo.objects[objKey]);
        } else {
            return;
        }

        this.stateLayer = L.geoJSON(geoFeatures, {
            style: (feature) => {
                const name = getFeatureName(feature);
                const r = name ? (regionMap[name] || regionMap[name?.toLowerCase()]) : null;
                const cases = r ? r.total_cases : 0;

                return {
                    fillColor: cases > 0 ? colorScale(cases) : '#1a1f2e',
                    fillOpacity: 0.8,
                    weight: 1,
                    color: '#2a3346',
                    opacity: 0.8,
                };
            },
            onEachFeature: (feature, layer) => {
                const name = getFeatureName(feature);
                const r = name ? (regionMap[name] || regionMap[name?.toLowerCase()]) : null;

                const popupContent = `
                    <div class="popup-country-name">${name || 'Unknown'}</div>
                    <div class="popup-stat">
                        <span class="popup-stat-label">Cases:</span>
                        <span class="popup-stat-value">${r ? Utils.formatNumber(r.total_cases) : '0'}</span>
                    </div>
                    ${r?.trend_pct != null ? `
                    <div class="popup-stat">
                        <span class="popup-stat-label">Trend:</span>
                        <span class="popup-stat-value ${Utils.trendClass(r.trend_pct)}">${Utils.trendArrow(r.trend_pct)} ${Utils.formatTrend(r.trend_pct)}</span>
                    </div>` : ''}
                    ${r?.population ? `
                    <div class="popup-stat">
                        <span class="popup-stat-label">Per 100k:</span>
                        <span class="popup-stat-value">${(r.total_cases / r.population * 100000).toFixed(1)}</span>
                    </div>` : ''}
                `;
                layer.bindPopup(popupContent);

                layer.on('mouseover', function () {
                    this.setStyle({ weight: 2, color: '#4a9eff' });
                    this.bringToFront();
                });
                layer.on('mouseout', function () {
                    this.setStyle({ weight: 1, color: '#2a3346' });
                });
            },
        }).addTo(this.map);

        // Zoom to the state layer bounds
        const bounds = this.stateLayer.getBounds();
        if (bounds.isValid()) {
            this.map.fitBounds(bounds, { padding: [20, 20] });
        }
    },

    /**
     * Clear the state choropleth layer and restore world view.
     */
    clearStateChoropleth() {
        if (this.stateLayer) {
            this.map.removeLayer(this.stateLayer);
            this.stateLayer = null;
        }
        this.regionLayer.clearLayers();
    },

    /**
     * Load state-level TopoJSON for a country (cached).
     */
    async _loadStateTopoJSON(countryCode) {
        if (this.stateTopoCache[countryCode]) {
            return this.stateTopoCache[countryCode];
        }

        let url;
        if (countryCode === 'US') {
            url = 'https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json';
        } else if (countryCode === 'BR') {
            url = 'data/brazil-states.json';
        } else {
            return null;
        }

        try {
            const resp = await fetch(url);
            if (!resp.ok) return null;
            const data = await resp.json();
            this.stateTopoCache[countryCode] = data;
            return data;
        } catch (e) {
            console.error(`Failed to load state TopoJSON for ${countryCode}`, e);
            return null;
        }
    },

    /**
     * Add pulsing markers for anomalies.
     */
    updateAnomalyMarkers(anomalies) {
        this.anomalyLayer.clearLayers();
        if (!anomalies) return;

        const centroids = this.countryCentroids || this._computeCountryCentroids();

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
        const labels = ['0', '0.1', '0.5', '1', '3', '10', '20', '40+'];
        const colors = ['#1a1f2e', '#0d3b66', '#1565c0', '#00897b', '#ffd700', '#ff8c00', '#ff4444', '#ff0040'];

        legend.innerHTML = `
            <span class="legend-label">${labels[0]}</span>
            <div class="legend-bar">
                ${colors.map(c => `<div class="segment" style="background:${c}"></div>`).join('')}
            </div>
            <span class="legend-label">${labels[labels.length - 1]}</span>
            <span class="legend-unit">per 100k</span>
        `;
    },

    // --- Private helpers ---

    /**
     * Fix antimeridian artifacts for countries like Russia and Fiji.
     * For each polygon ring, if consecutive points jump > 180° in longitude,
     * shift coordinates so the entire ring stays on one side.
     */
    _fixAntimeridian(geojson) {
        const fixRing = (ring) => {
            for (let i = 1; i < ring.length; i++) {
                const diff = ring[i][0] - ring[i - 1][0];
                if (diff > 180) {
                    ring[i][0] -= 360;
                } else if (diff < -180) {
                    ring[i][0] += 360;
                }
            }
        };

        const fixCoords = (geometry) => {
            if (!geometry) return;
            if (geometry.type === 'Polygon') {
                geometry.coordinates.forEach(fixRing);
            } else if (geometry.type === 'MultiPolygon') {
                geometry.coordinates.forEach(polygon => {
                    polygon.forEach(fixRing);
                });
            }
        };

        if (geojson.type === 'FeatureCollection') {
            geojson.features.forEach(f => fixCoords(f.geometry));
        } else if (geojson.type === 'Feature') {
            fixCoords(geojson.geometry);
        }
    },

    _getMetricValue(data) {
        if (!data) return 0;
        return data.cases_per_100k || 0;
    },

    _createPopup(data) {
        return `
            <div class="popup-country-name">${data.country_name}</div>
            <div class="popup-stat">
                <span class="popup-stat-label">Per 100k:</span>
                <span class="popup-stat-value">${data.cases_per_100k != null ? data.cases_per_100k.toFixed(2) : '—'}</span>
            </div>
            <div class="popup-stat">
                <span class="popup-stat-label">Cases (14d):</span>
                <span class="popup-stat-value">${Utils.formatNumber(data.new_cases_7d)}</span>
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
        // Complete mapping of ISO 3166-1 numeric codes to ISO2 alpha-2 codes.
        // world-atlas TopoJSON uses numeric IDs (sometimes zero-padded strings
        // like "076"), so we index by integer and resolve via _resolveCountryCode().
        const numericToAlpha2 = {
            4: 'AF', 8: 'AL', 10: 'AQ', 12: 'DZ', 16: 'AS', 20: 'AD',
            24: 'AO', 28: 'AG', 31: 'AZ', 32: 'AR', 36: 'AU', 40: 'AT',
            44: 'BS', 48: 'BH', 50: 'BD', 51: 'AM', 52: 'BB', 56: 'BE',
            60: 'BM', 64: 'BT', 68: 'BO', 70: 'BA', 72: 'BW', 76: 'BR',
            84: 'BZ', 86: 'IO', 90: 'SB', 92: 'VG', 96: 'BN', 100: 'BG',
            104: 'MM', 108: 'BI', 112: 'BY', 116: 'KH', 120: 'CM', 124: 'CA',
            132: 'CV', 136: 'KY', 140: 'CF', 144: 'LK', 148: 'TD', 152: 'CL',
            156: 'CN', 158: 'TW', 162: 'CX', 166: 'CC', 170: 'CO', 174: 'KM',
            175: 'YT', 178: 'CG', 180: 'CD', 184: 'CK', 188: 'CR', 191: 'HR',
            192: 'CU', 196: 'CY', 203: 'CZ', 204: 'BJ', 208: 'DK', 212: 'DM',
            214: 'DO', 218: 'EC', 222: 'SV', 226: 'GQ', 231: 'ET', 232: 'ER',
            233: 'EE', 234: 'FO', 238: 'FK', 242: 'FJ', 246: 'FI', 248: 'AX',
            250: 'FR', 254: 'GF', 258: 'PF', 260: 'TF', 262: 'DJ', 266: 'GA',
            268: 'GE', 270: 'GM', 275: 'PS', 276: 'DE', 288: 'GH', 292: 'GI',
            296: 'KI', 300: 'GR', 304: 'GL', 308: 'GD', 312: 'GP', 316: 'GU',
            320: 'GT', 324: 'GN', 328: 'GY', 332: 'HT', 336: 'VA', 340: 'HN',
            344: 'HK', 348: 'HU', 352: 'IS', 356: 'IN', 360: 'ID', 364: 'IR',
            368: 'IQ', 372: 'IE', 376: 'IL', 380: 'IT', 384: 'CI', 388: 'JM',
            392: 'JP', 398: 'KZ', 400: 'JO', 404: 'KE', 408: 'KP', 410: 'KR',
            414: 'KW', 417: 'KG', 418: 'LA', 422: 'LB', 426: 'LS', 428: 'LV',
            430: 'LR', 434: 'LY', 438: 'LI', 440: 'LT', 442: 'LU', 446: 'MO',
            450: 'MG', 454: 'MW', 458: 'MY', 462: 'MV', 466: 'ML', 470: 'MT',
            474: 'MQ', 478: 'MR', 480: 'MU', 484: 'MX', 492: 'MC', 496: 'MN',
            498: 'MD', 499: 'ME', 500: 'MS', 504: 'MA', 508: 'MZ', 512: 'OM',
            516: 'NA', 520: 'NR', 524: 'NP', 528: 'NL', 531: 'CW', 533: 'AW',
            534: 'SX', 540: 'NC', 548: 'VU', 554: 'NZ', 558: 'NI', 562: 'NE',
            566: 'NG', 570: 'NU', 574: 'NF', 578: 'NO', 580: 'MP', 581: 'UM',
            583: 'FM', 584: 'MH', 585: 'PW', 586: 'PK', 591: 'PA', 598: 'PG',
            600: 'PY', 604: 'PE', 608: 'PH', 612: 'PN', 616: 'PL', 620: 'PT',
            624: 'GW', 626: 'TL', 630: 'PR', 634: 'QA', 638: 'RE', 642: 'RO',
            643: 'RU', 646: 'RW', 652: 'BL', 654: 'SH', 659: 'KN', 660: 'AI',
            662: 'LC', 663: 'MF', 666: 'PM', 670: 'VC', 674: 'SM', 678: 'ST',
            682: 'SA', 686: 'SN', 688: 'RS', 690: 'SC', 694: 'SL', 702: 'SG',
            703: 'SK', 704: 'VN', 705: 'SI', 706: 'SO', 710: 'ZA', 716: 'ZW',
            724: 'ES', 728: 'SS', 729: 'SD', 732: 'EH', 740: 'SR', 744: 'SJ',
            748: 'SZ', 752: 'SE', 756: 'CH', 760: 'SY', 762: 'TJ', 764: 'TH',
            768: 'TG', 772: 'TK', 776: 'TO', 780: 'TT', 784: 'AE', 788: 'TN',
            792: 'TR', 795: 'TM', 796: 'TC', 798: 'TV', 800: 'UG', 804: 'UA',
            807: 'MK', 818: 'EG', 826: 'GB', 831: 'GG', 832: 'JE', 833: 'IM',
            834: 'TZ', 840: 'US', 850: 'VI', 854: 'BF', 858: 'UY', 860: 'UZ',
            862: 'VE', 876: 'WF', 882: 'WS', 887: 'YE', 894: 'ZM',
            // Kosovo (user-assigned code, used by world-atlas)
            '-99': 'XK',
        };
        return numericToAlpha2;
    },

    _manualCentroidOverrides() {
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
            BE: [50.8, 4.5], HU: [47.2, 19.5], SE: [62.1, 15.0],
        };
    },

    _computeCountryCentroids() {
        if (!this.topoData) return this._manualCentroidOverrides();

        const iso3to2 = this._buildIso3to2Map();
        const geoFeatures = topojson.feature(this.topoData, this.topoData.objects.countries);
        const centroids = {};

        geoFeatures.features.forEach((feature) => {
            const code2 = iso3to2[feature.id] || iso3to2[parseInt(feature.id, 10)];
            if (!code2 || !feature.geometry) return;
            const [lng, lat] = d3.geoCentroid(feature);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
            centroids[code2] = [lat, lng];
        });

        // Keep manual values as fallback/override for problematic geometries.
        return { ...centroids, ...this._manualCentroidOverrides() };
    },
};
