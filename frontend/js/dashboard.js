/**
 * Dashboard table module for FluTracker.
 * Renders the sortable/filterable country data table with sparklines.
 * Supports expandable region sub-rows for countries with state-level data.
 */

const Dashboard = {
    countries: [],
    filtered: [],
    severityMap: {},
    trendDataCache: {},
    selectedCode: null,
    countriesWithRegions: new Set(),
    expandedCountries: {},  // code -> regionData cache
    expandedSet: new Set(),  // currently expanded codes

    init() {
        // Search
        document.getElementById('searchInput').addEventListener(
            'input',
            Utils.debounce(() => this.applyFilters(), 200)
        );

        // Filters
        ['filterContinent', 'filterFluType', 'sortBy'].forEach(id => {
            document.getElementById(id).addEventListener('change', () => this.applyFilters());
        });

        // Sortable headers
        document.querySelectorAll('.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const sort = th.dataset.sort;
                const select = document.getElementById('sortBy');
                // Toggle asc/desc
                if (select.value === `${sort}_desc`) {
                    select.value = `${sort}_asc`;
                } else {
                    select.value = `${sort}_desc`;
                }
                this.applyFilters();
            });
        });
    },

    /**
     * Load country data and render table.
     */
    async update(countries, severityData) {
        this.countries = countries || [];

        // Build severity map
        this.severityMap = {};
        if (severityData) {
            severityData.forEach(s => {
                this.severityMap[s.country_code] = s;
            });
        }

        this.applyFilters();
    },

    /**
     * Apply search, filter, and sort, then render.
     */
    applyFilters() {
        const search = document.getElementById('searchInput').value.toLowerCase();
        const continent = document.getElementById('filterContinent').value;
        const fluType = document.getElementById('filterFluType').value;
        const sortBy = document.getElementById('sortBy').value;

        let data = [...this.countries];

        // Search filter
        if (search) {
            data = data.filter(c =>
                c.name.toLowerCase().includes(search) ||
                c.code.toLowerCase().includes(search)
            );
        }

        // Continent filter
        if (continent) {
            data = data.filter(c => c.continent === continent);
        }

        // Flu type filter — match against dominant type from severity data
        if (fluType) {
            data = data.filter(c => {
                const sev = this.severityMap[c.code];
                const dominant = sev?.components?.dominant_type || '';
                return dominant.toLowerCase().includes(fluType.toLowerCase());
            });
        }

        // Sort
        const [field, dir] = sortBy.split('_');
        const mult = dir === 'asc' ? 1 : -1;

        data.sort((a, b) => {
            switch (field) {
                case 'cases':
                    return mult * ((a.total_recent_cases || 0) - (b.total_recent_cases || 0));
                case 'trend':
                    return mult * ((a.trend_pct || 0) - (b.trend_pct || 0));
                case 'severity': {
                    const sa = this.severityMap[a.code]?.score || 0;
                    const sb = this.severityMap[b.code]?.score || 0;
                    return mult * (sa - sb);
                }
                case 'rate': {
                    const ra = a.population ? (a.total_recent_cases || 0) / a.population * 100000 : 0;
                    const rb = b.population ? (b.total_recent_cases || 0) / b.population * 100000 : 0;
                    return mult * (ra - rb);
                }
                case 'name':
                    return mult * a.name.localeCompare(b.name);
                default:
                    return mult * ((a.total_recent_cases || 0) - (b.total_recent_cases || 0));
            }
        });

        this.filtered = data;
        this.render();
    },

    /**
     * Render the table body.
     */
    render() {
        const tbody = document.getElementById('dashboardBody');

        if (this.filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">No matching countries</td></tr>';
            return;
        }

        tbody.innerHTML = this.filtered.map((c, idx) => {
            const severity = this.severityMap[c.code];
            const severityScore = severity?.score || 0;
            const severityLevel = severity?.level || 'low';
            const per100k = c.population
                ? ((c.total_recent_cases || 0) / c.population * 100000).toFixed(1)
                : '—';
            const hasRegions = this.countriesWithRegions.has(c.code);
            const isExpanded = this.expandedSet.has(c.code);
            const chevron = hasRegions
                ? `<span class="expand-toggle">${isExpanded ? '&#9662;' : '&#9656;'}</span> `
                : '';

            let html = `
                <tr data-code="${c.code}" class="${c.code === this.selectedCode ? 'selected' : ''}">
                    <td class="col-rank">${idx + 1}</td>
                    <td class="col-country">${chevron}${c.name}</td>
                    <td class="col-cases">${Utils.formatNumber(c.total_recent_cases || 0)}</td>
                    <td class="col-rate">${per100k}</td>
                    <td class="col-trend ${Utils.trendClass(c.trend_pct)}">
                        ${Utils.trendArrow(c.trend_pct)} ${Utils.formatTrend(c.trend_pct)}
                    </td>
                    <td class="col-sparkline">
                        <svg class="sparkline-svg" data-code="${c.code}" width="90" height="24"></svg>
                    </td>
                    <td class="col-severity">
                        <div class="severity-bar">
                            <div class="severity-meter">
                                <div class="severity-fill" style="
                                    width: ${severityScore}%;
                                    background: ${Utils.severityScoreColor(severityScore)};
                                "></div>
                            </div>
                            <span class="severity-label" style="color: ${Utils.severityColor(severityLevel)}">
                                ${Math.round(severityScore)}
                            </span>
                        </div>
                    </td>
                    <td class="col-subtypes">
                        ${severity?.components?.dominant_type || '—'}
                    </td>
                </tr>
            `;

            // Render expanded region sub-rows
            if (isExpanded && this.expandedCountries[c.code]) {
                const regions = this.expandedCountries[c.code];
                html += regions.map(r => {
                    const rPer100k = r.population
                        ? (r.total_cases / r.population * 100000).toFixed(1)
                        : '—';
                    const dominantType = r.flu_types
                        ? Object.entries(r.flu_types).sort((a, b) => b[1] - a[1])[0]?.[0] || '—'
                        : '—';
                    return `
                        <tr class="region-row" data-country="${c.code}" data-region="${r.region}">
                            <td class="col-rank"></td>
                            <td class="col-country region-name">${r.region}</td>
                            <td class="col-cases">${Utils.formatNumber(r.total_cases)}</td>
                            <td class="col-rate">${rPer100k}</td>
                            <td class="col-trend ${r.trend_pct != null ? Utils.trendClass(r.trend_pct) : ''}">
                                ${r.trend_pct != null ? Utils.trendArrow(r.trend_pct) + ' ' + Utils.formatTrend(r.trend_pct) : '—'}
                            </td>
                            <td class="col-sparkline"></td>
                            <td class="col-severity"></td>
                            <td class="col-subtypes">${dominantType}</td>
                        </tr>
                    `;
                }).join('');
            }

            return html;
        }).join('');

        // Row click handlers for country rows
        tbody.querySelectorAll('tr[data-code]:not(.region-row)').forEach(row => {
            row.addEventListener('click', (e) => {
                const code = row.dataset.code;

                // If clicking on expand toggle area (or the chevron itself)
                if (this.countriesWithRegions.has(code)) {
                    const toggle = row.querySelector('.expand-toggle');
                    if (toggle && (e.target === toggle || e.target.closest('.col-country'))) {
                        this._toggleExpand(code);
                        return;
                    }
                }

                const country = this.filtered.find(c => c.code === code);
                this.selectedCode = code;

                // Highlight selected row
                tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                row.classList.add('selected');

                // Trigger country selection
                FluMap.selectCountry(code, country?.name || code);
            });
        });

        // Draw sparklines
        this._drawSparklines();
    },

    /**
     * Toggle expand/collapse for a country's region rows.
     */
    async _toggleExpand(code) {
        if (this.expandedSet.has(code)) {
            this.expandedSet.delete(code);
            this.render();
            return;
        }

        // Fetch region data if not cached
        if (!this.expandedCountries[code]) {
            // Show loading row while fetching
            this.expandedSet.add(code);
            this.expandedCountries[code] = [{
                region: 'Loading...', total_cases: 0, flu_types: null,
                lat: null, lon: null, trend_pct: null, population: null, _loading: true,
            }];
            this.render();

            const data = await API.getCasesByRegion(code);
            if (data && data.regions) {
                this.expandedCountries[code] = data.regions;
            } else {
                this.expandedSet.delete(code);
                delete this.expandedCountries[code];
            }
            this.render();
            return;
        }

        this.expandedSet.add(code);
        this.render();
    },

    /**
     * Draw mini sparkline charts in table cells.
     */
    _drawSparklines() {
        document.querySelectorAll('.sparkline-svg').forEach(async (svgEl) => {
            const code = svgEl.dataset.code;
            const svg = d3.select(svgEl);
            svg.selectAll('*').remove();

            // Use cached data or fetch
            let data;
            if (this.trendDataCache[code]) {
                data = this.trendDataCache[code];
            } else {
                const trend = await API.getTrends(code, 'week', 12);
                data = trend?.data?.map(d => d.cases) || [];
                this.trendDataCache[code] = data;
            }

            if (data.length < 2) return;

            const w = 90, h = 24, pad = 2;
            const x = d3.scaleLinear().domain([0, data.length - 1]).range([pad, w - pad]);
            const y = d3.scaleLinear().domain([0, d3.max(data) || 1]).range([h - pad, pad]);

            const line = d3.line()
                .x((d, i) => x(i))
                .y(d => y(d))
                .curve(d3.curveMonotoneX);

            // Determine color from trend
            const last = data[data.length - 1];
            const prev = data[data.length - 2];
            const color = last > prev * 1.05 ? '#ff4444' : last < prev * 0.95 ? '#00c853' : '#4a9eff';

            svg.append('path')
                .datum(data)
                .attr('d', line)
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 1.5);

            // End dot
            svg.append('circle')
                .attr('cx', x(data.length - 1))
                .attr('cy', y(last))
                .attr('r', 2.5)
                .attr('fill', color);
        });
    },
};
