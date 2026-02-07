/**
 * Forecast chart module for FluTracker.
 * Draws trendline with projected future values and confidence intervals.
 */

const Forecast = {
    /**
     * Draw forecast chart for the selected country.
     */
    async draw() {
        const country = Charts.currentCountry;
        if (!country) {
            Charts._drawEmpty('Select a country to view forecast');
            return;
        }

        // Fetch historical trend and forecast
        const [trendData, forecastData] = await Promise.all([
            API.getTrends(country, 'week', 24),
            API.getForecast(country, 4),
        ]);

        if (!trendData || !trendData.data || trendData.data.length === 0) {
            Charts._drawEmpty('Insufficient data for forecast');
            return;
        }

        document.getElementById('chartTitle').textContent = `Forecast: ${country}`;

        const svg = Charts.svg;
        svg.selectAll('*').remove();

        const margin = Charts.margin;
        const width = Charts.width;
        const height = Charts.height;

        const g = svg.append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');

        // Historical points
        const historical = trendData.data.map(d => ({
            date: parseDate(d.date),
            cases: d.cases,
            type: 'historical',
        }));

        // Forecast points
        const forecast = forecastData && forecastData.data
            ? forecastData.data.map(d => ({
                date: parseDate(d.date),
                cases: d.predicted_cases,
                lower80: d.lower_80,
                upper80: d.upper_80,
                lower95: d.lower_95,
                upper95: d.upper_95,
                type: 'forecast',
            }))
            : [];

        const allPoints = [...historical, ...forecast];

        if (allPoints.length === 0) {
            Charts._drawEmpty('No data available');
            return;
        }

        // Scales
        const x = d3.scaleTime()
            .domain(d3.extent(allPoints, d => d.date))
            .range([0, width]);

        const maxY = d3.max(allPoints, d => {
            return d.type === 'forecast' ? (d.upper95 || d.cases) : d.cases;
        });

        const y = d3.scaleLinear()
            .domain([0, maxY * 1.1])
            .nice()
            .range([height, 0]);

        // Grid
        g.append('g')
            .attr('class', 'grid')
            .call(d3.axisLeft(y).tickSize(-width).tickFormat(''));

        // 95% CI band
        if (forecast.length > 0) {
            const ciData95 = forecast.filter(d => d.lower95 != null);
            if (ciData95.length > 0) {
                const ci95Area = d3.area()
                    .x(d => x(d.date))
                    .y0(d => y(d.lower95))
                    .y1(d => y(d.upper95))
                    .curve(d3.curveMonotoneX);

                g.append('path')
                    .datum(ciData95)
                    .attr('class', 'forecast-ci forecast-ci-95')
                    .attr('d', ci95Area);
            }

            // 80% CI band
            const ciData80 = forecast.filter(d => d.lower80 != null);
            if (ciData80.length > 0) {
                const ci80Area = d3.area()
                    .x(d => x(d.date))
                    .y0(d => y(d.lower80))
                    .y1(d => y(d.upper80))
                    .curve(d3.curveMonotoneX);

                g.append('path')
                    .datum(ciData80)
                    .attr('class', 'forecast-ci forecast-ci-80')
                    .attr('d', ci80Area);
            }
        }

        // Historical line
        const histLine = d3.line()
            .x(d => x(d.date))
            .y(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(historical)
            .attr('class', 'trend-line')
            .attr('d', histLine);

        // Historical area
        const histArea = d3.area()
            .x(d => x(d.date))
            .y0(height)
            .y1(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(historical)
            .attr('class', 'trend-area')
            .attr('d', histArea);

        // Forecast line
        if (forecast.length > 0) {
            // Connect from last historical point
            const forecastWithBridge = [historical[historical.length - 1], ...forecast];

            g.append('path')
                .datum(forecastWithBridge)
                .attr('class', 'forecast-line')
                .attr('d', histLine);

            // Forecast dots
            g.selectAll('.forecast-dot')
                .data(forecast)
                .join('circle')
                .attr('cx', d => x(d.date))
                .attr('cy', d => y(d.cases))
                .attr('r', 4)
                .attr('fill', 'none')
                .attr('stroke', '#00d4aa')
                .attr('stroke-width', 2)
                .attr('stroke-dasharray', '3 3');
        }

        // Divider line between historical and forecast
        if (historical.length > 0 && forecast.length > 0) {
            const dividerX = x(historical[historical.length - 1].date);
            g.append('line')
                .attr('x1', dividerX).attr('x2', dividerX)
                .attr('y1', 0).attr('y2', height)
                .attr('stroke', '#5f6368')
                .attr('stroke-dasharray', '4 4')
                .attr('opacity', 0.5);

            g.append('text')
                .attr('x', dividerX + 4)
                .attr('y', 12)
                .attr('fill', '#5f6368')
                .attr('font-size', '10px')
                .text('Forecast →');
        }

        // Peak marker
        if (forecastData && forecastData.peak_date) {
            const peakDate = parseDate(forecastData.peak_date);
            const peakVal = forecastData.peak_magnitude;
            if (peakDate && x(peakDate) > 0 && x(peakDate) < width) {
                g.append('line')
                    .attr('x1', x(peakDate)).attr('x2', x(peakDate))
                    .attr('y1', y(peakVal) - 15).attr('y2', y(peakVal) + 15)
                    .attr('stroke', '#ff8c00')
                    .attr('stroke-width', 2);

                g.append('text')
                    .attr('x', x(peakDate))
                    .attr('y', y(peakVal) - 20)
                    .attr('text-anchor', 'middle')
                    .attr('fill', '#ff8c00')
                    .attr('font-size', '11px')
                    .text(`Peak: ${Utils.formatNumber(peakVal)}`);
            }
        }

        // Legend
        const legend = g.append('g')
            .attr('transform', `translate(${width - 150}, 5)`);

        const legendItems = [
            { label: 'Actual', color: '#00d4aa', dash: '' },
            { label: 'Forecast', color: '#00d4aa', dash: '8 4' },
            { label: '80% CI', color: '#00d4aa', dash: '', opacity: 0.15 },
            { label: '95% CI', color: '#4a9eff', dash: '', opacity: 0.15 },
        ];

        legendItems.forEach((item, i) => {
            const row = legend.append('g').attr('transform', `translate(0, ${i * 16})`);
            if (item.opacity) {
                row.append('rect')
                    .attr('width', 20).attr('height', 10).attr('y', -5)
                    .attr('fill', item.color).attr('opacity', item.opacity);
            } else {
                row.append('line')
                    .attr('x1', 0).attr('x2', 20).attr('y1', 0).attr('y2', 0)
                    .attr('stroke', item.color).attr('stroke-width', 2)
                    .attr('stroke-dasharray', item.dash);
            }
            row.append('text')
                .attr('x', 26).attr('y', 4)
                .attr('fill', '#9aa0a6').attr('font-size', '10px')
                .text(item.label);
        });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat('%b %d')));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(',.0f')));
    },
};

// Hook into Charts module
Charts.drawForecast = Forecast.draw.bind(Forecast);
