/**
 * D3 chart module for FluTracker.
 * Renders trendlines, subtype stacked areas, and historical overlays.
 */

const Charts = {
    svg: null,
    margin: { top: 20, right: 30, bottom: 40, left: 60 },
    width: 0,
    height: 0,
    currentView: 'historical',
    currentCountry: null,
    tooltip: null,

    init() {
        this.svg = d3.select('#mainChart');
        this.tooltip = d3.select('#chartContainer')
            .append('div')
            .attr('class', 'chart-tooltip')
            .style('display', 'none');

        this._updateDimensions();
        window.addEventListener('resize', Utils.debounce(() => {
            this._updateDimensions();
            this.refresh();
        }, 250));

        // Chart view buttons
        document.querySelectorAll('.chart-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.chart-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.currentView = e.target.dataset.view;
                this.refresh();

                // Show/hide compare selector
                document.getElementById('compareSelector').style.display =
                    this.currentView === 'compare' ? 'flex' : 'none';
            });
        });
    },

    _updateDimensions() {
        const container = document.getElementById('chartContainer');
        const rect = container.getBoundingClientRect();
        this.width = rect.width - this.margin.left - this.margin.right;
        this.height = rect.height - this.margin.top - this.margin.bottom;
    },

    /**
     * Refresh current chart view with latest data.
     */
    async refresh() {
        this._updateDimensions();
        switch (this.currentView) {
            case 'subtype':
                await this.drawSubtypeChart();
                break;
            case 'historical':
                await this.drawHistoricalOverlay();
                break;
            case 'compare':
                await Comparison.draw();
                break;
            default:
                await this.drawHistoricalOverlay();
                break;
        }
    },

    /**
     * Draw the main trendline chart.
     */
    async drawTrendline() {
        const data = this.currentCountry
            ? await API.getTrends(this.currentCountry)
            : await API.getGlobalTrends();

        if (!data || !data.data || data.data.length === 0) {
            this._drawEmpty('No trend data available');
            return;
        }

        const title = this.currentCountry
            ? `Trend: ${this.currentCountry}`
            : 'Global Trend';
        document.getElementById('chartTitle').textContent = title;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');
        const points = data.data.map(d => ({
            date: parseDate(d.date),
            cases: d.cases,
            per100k: d.cases_per_100k,
        }));

        const x = d3.scaleTime()
            .domain(d3.extent(points, d => d.date))
            .range([0, this.width]);

        const y = d3.scaleLinear()
            .domain([0, d3.max(points, d => d.cases) * 1.1])
            .nice()
            .range([this.height, 0]);

        // Line
        const line = d3.line()
            .x(d => x(d.date))
            .y(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        const trendPath = g.append('path')
            .datum(points)
            .attr('class', 'trend-line')
            .attr('d', line);

        // Draw-in animation
        const totalLength = trendPath.node().getTotalLength();
        trendPath
            .attr('stroke-dasharray', totalLength)
            .attr('stroke-dashoffset', totalLength)
            .transition()
            .duration(1200)
            .ease(d3.easeCubicOut)
            .attr('stroke-dashoffset', 0);

        // Dots
        const dots = g.selectAll('.dot')
            .data(points)
            .join('circle')
            .attr('cx', d => x(d.date))
            .attr('cy', d => y(d.cases))
            .attr('r', 0)
            .attr('fill', '#00d4aa')
            .attr('stroke', '#1e2538')
            .attr('stroke-width', 2);

        dots.transition()
            .duration(300)
            .delay((d, i) => 800 + i * 30)
            .attr('r', 4);

        dots.on('mouseover', (event, d) => {
                this.tooltip
                    .style('display', 'block')
                    .html(`
                        <div class="tooltip-date">${Utils.formatDate(d.date)}</div>
                        <div class="tooltip-value">${Utils.formatNumber(d.cases)} cases</div>
                    `)
                    .style('left', (event.offsetX + 15) + 'px')
                    .style('top', (event.offsetY - 10) + 'px');
            })
            .on('mouseout', () => {
                this.tooltip.style('display', 'none');
            });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${this.height})`)
            .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat('%b %d')));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(',.0f')));
    },

    /**
     * Draw subtype stacked area chart.
     */
    async drawSubtypeChart() {
        const data = await API.getFluTypes(this.currentCountry, 84); // 12 weeks
        if (!data || !data.breakdown || data.breakdown.length === 0) {
            this._drawEmpty('No subtype data available');
            return;
        }

        document.getElementById('chartTitle').textContent =
            `Flu Subtypes${this.currentCountry ? ': ' + this.currentCountry : ''}`;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        // Draw as a clean ranked list (no bars) to reduce chart noise.
        const y = d3.scaleBand()
            .domain(data.breakdown.map(d => d.flu_type))
            .range([0, this.height])
            .padding(0.35);

        const x = d3.scaleLinear()
            .domain([0, d3.max(data.breakdown, d => d.percentage)])
            .range([0, this.width]);

        g.selectAll('.subtype-dot')
            .data(data.breakdown)
            .join('circle')
            .attr('class', 'subtype-dot')
            .attr('cy', d => y(d.flu_type) + y.bandwidth() / 2)
            .attr('cx', 0)
            .attr('r', 0)
            .attr('fill', d => Utils.fluTypeColor(d.flu_type))
            .transition()
            .duration(450)
            .delay((d, i) => i * 60)
            .ease(d3.easeCubicOut)
            .attr('r', 5);

        // Labels
        g.selectAll('.bar-label')
            .data(data.breakdown)
            .join('text')
            .attr('y', d => y(d.flu_type) + y.bandwidth() / 2)
            .attr('x', d => x(d.percentage) + 8)
            .attr('dy', '0.35em')
            .attr('fill', '#9aa0a6')
            .attr('font-size', '12px')
            .text(d => `${d.percentage.toFixed(1)}% (${Utils.formatNumber(d.count)})`);

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y))
            .selectAll('text')
            .attr('fill', '#e8eaed');
    },

    /**
     * Draw historical overlay — current season vs past seasons.
     */
    async drawHistoricalOverlay() {
        const [result, forecastResult] = await Promise.all([
            // Show 10 total seasons: current + previous 9.
            API.getHistoricalSeasons(this.currentCountry, 9),
            this.currentCountry ? API.getForecast(this.currentCountry, 4) : Promise.resolve(null),
        ]);

        if (!result || !result.current_season || result.current_season.data.length === 0) {
            this._drawEmpty('No historical data available');
            return;
        }

        document.getElementById('chartTitle').textContent =
            `Historical Comparison${this.currentCountry ? ': ' + this.currentCountry : ''}`;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');
        const normalizeSeasonDate = (date) => {
            const month = date.getMonth();
            const day = date.getDate();
            return month >= 9 ? new Date(2000, month, day) : new Date(2001, month, day);
        };
        const parseHistoricalPointDate = (rawDate) => {
            if (rawDate == null) return null;

            // Preferred API shape: YYYY-MM-DD
            const parsed = parseDate(rawDate);
            if (parsed) return normalizeSeasonDate(parsed);

            // Accept full ISO datetime strings as fallback.
            const iso = new Date(rawDate);
            if (!Number.isNaN(iso.getTime())) return normalizeSeasonDate(iso);

            // Backward compatibility: legacy week-offset index ("0", "1", ...).
            const weekOffset = Number.parseInt(rawDate, 10);
            if (Number.isFinite(weekOffset)) return new Date(2000, 9, 1 + weekOffset * 7);

            return null;
        };
        const mapSeasonData = (season) => season.data
            .map(d => {
                const seasonDate = parseHistoricalPointDate(d.date);
                if (!seasonDate) return null;
                return {
                    ...d,
                    seasonDate,
                };
            })
            .filter(Boolean)
            .sort((a, b) => a.seasonDate - b.seasonDate);

        const currentData = mapSeasonData(result.current_season);
        const pastSeasons = (result.past_seasons || [])
            .map(s => ({ ...s, data: mapSeasonData(s) }));
        const forecastData = (forecastResult && forecastResult.data ? forecastResult.data : [])
            .map(d => {
                const seasonDate = parseHistoricalPointDate(d.date);
                if (!seasonDate) return null;
                return {
                    cases: d.predicted_cases,
                    upper95: d.upper_95,
                    seasonDate,
                };
            })
            .filter(Boolean)
            .sort((a, b) => a.seasonDate - b.seasonDate);
        const allSeasons = [currentData, ...pastSeasons.map(s => s.data)].filter(s => s.length > 0);

        if (allSeasons.length === 0 || currentData.length === 0) {
            this._drawEmpty('No historical data available');
            return;
        }

        const seasonStart = new Date(2000, 9, 1); // Oct 1
        const seasonEnd = new Date(2001, 8, 30); // Sep 30
        const x = d3.scaleTime()
            .domain([seasonStart, seasonEnd])
            .range([0, this.width]);

        // Find max cases across all seasons for y domain
        let maxCases = 0;
        allSeasons.forEach(s => {
            s.forEach(d => { if (d.cases > maxCases) maxCases = d.cases; });
        });
        forecastData.forEach(d => {
            const ceiling = d.upper95 != null ? d.upper95 : d.cases;
            if (ceiling > maxCases) maxCases = ceiling;
        });

        const y = d3.scaleLinear()
            .domain([0, maxCases * 1.2])
            .nice()
            .range([this.height, 0]);

        const line = d3.line()
            .x(d => x(d.seasonDate))
            .y(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        // Historical range band removed to keep the chart visually clean.
        if (pastSeasons.length > 0) {
            // Historical season lines
            const historicalColors = ['#5f6368', '#4a4f5a', '#3a3f4a', '#2a2f3a', '#6b7280'];
            pastSeasons.forEach((season, idx) => {
                if (season.data.length > 0) {
                    g.append('path')
                        .datum(season.data)
                        .attr('class', 'historical-line')
                        .attr('d', line)
                        .attr('stroke', historicalColors[idx % historicalColors.length]);
                }
            });
        }

        // Current season (bold line)
        if (currentData.length > 0) {
            const currentPath = g.append('path')
                .datum(currentData)
                .attr('class', 'trend-line')
                .attr('d', line);

            const currentLen = currentPath.node().getTotalLength();
            currentPath
                .attr('stroke-dasharray', currentLen)
                .attr('stroke-dashoffset', currentLen)
                .transition()
                .duration(1200)
                .ease(d3.easeCubicOut)
                .attr('stroke-dashoffset', 0);
        }

        // Show season label when hovering/clicking a historical line.
        const interactiveSeasons = [
            { label: result.current_season.label, data: currentData, color: '#00d4aa', className: 'trend-line' },
            ...pastSeasons.map((s, i) => ({
                label: s.label,
                data: s.data,
                color: ['#5f6368', '#4a4f5a', '#3a3f4a', '#2a2f3a', '#6b7280'][i % 5],
                className: 'historical-line',
            })),
        ].filter(s => s.data && s.data.length > 0);

        let pinnedSeasonLabel = null;
        interactiveSeasons.forEach((season) => {
            g.append('path')
                .datum(season.data)
                .attr('class', season.className)
                .attr('d', line)
                .attr('stroke', season.color)
                .attr('stroke-width', season.className === 'trend-line' ? 3.5 : 2.6)
                .attr('fill', 'none')
                .attr('opacity', 0)
                .style('pointer-events', 'stroke')
                .on('mousemove', (event) => {
                    if (pinnedSeasonLabel) return;
                    this.tooltip
                        .style('display', 'block')
                        .html(`
                            <div class="tooltip-date">Season ${season.label}</div>
                        `)
                        .style('left', `${event.offsetX + 15}px`)
                        .style('top', `${event.offsetY - 10}px`);
                })
                .on('mouseleave', () => {
                    if (!pinnedSeasonLabel) {
                        this.tooltip.style('display', 'none');
                    }
                })
                .on('click', (event) => {
                    pinnedSeasonLabel = pinnedSeasonLabel === season.label ? null : season.label;
                    if (pinnedSeasonLabel) {
                        this.tooltip
                            .style('display', 'block')
                            .html(`
                                <div class="tooltip-date">Season ${season.label}</div>
                                <div class="tooltip-value">Pinned</div>
                            `)
                            .style('left', `${event.offsetX + 15}px`)
                            .style('top', `${event.offsetY - 10}px`);
                    } else {
                        this.tooltip.style('display', 'none');
                    }
                });
        });

        // Forecast extension (dotted line) for selected country.
        if (currentData.length > 0 && forecastData.length > 0) {
            const lastCurrentDate = currentData[currentData.length - 1].seasonDate;
            const futureForecast = forecastData.filter(d => d.seasonDate > lastCurrentDate);
            if (futureForecast.length > 0) {
                g.append('path')
                    .datum([currentData[currentData.length - 1], ...futureForecast])
                    .attr('class', 'forecast-line')
                    .attr('d', line);
            }
        }

        // Legend
        const legendData = [
            { label: result.current_season.label, color: '#00d4aa', dash: '' },
            ...pastSeasons.map((s, i) => ({
                label: s.label,
                color: ['#5f6368', '#4a4f5a', '#3a3f4a', '#2a2f3a', '#6b7280'][i % 5],
                dash: '4 2',
            })),
        ];
        if (currentData.length > 0 && forecastData.length > 0) {
            legendData.push({ label: 'Forecast', color: '#00d4aa', dash: '8 4' });
        }
        const legend = g.append('g')
            .attr('transform', `translate(${this.width - 160}, 5)`);

        legendData.forEach((d, i) => {
            const row = legend.append('g').attr('transform', `translate(0, ${i * 18})`);
            row.append('line')
                .attr('x1', 0).attr('x2', 20).attr('y1', 0).attr('y2', 0)
                .attr('stroke', d.color).attr('stroke-width', 2)
                .attr('stroke-dasharray', d.dash);
            row.append('text')
                .attr('x', 26).attr('y', 4)
                .attr('fill', '#9aa0a6').attr('font-size', '11px')
                .text(d.label);
        });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${this.height})`)
            .call(d3.axisBottom(x)
                .ticks(d3.timeMonth.every(1))
                .tickFormat(d3.timeFormat('%b')));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(',.0f')));
    },

    /**
     * Draw empty state message.
     */
    _drawEmpty(message) {
        this.svg.selectAll('*').remove();
        this.svg.append('text')
            .attr('x', '50%')
            .attr('y', '50%')
            .attr('text-anchor', 'middle')
            .attr('fill', '#5f6368')
            .attr('font-size', '14px')
            .text(message);
    },
};
