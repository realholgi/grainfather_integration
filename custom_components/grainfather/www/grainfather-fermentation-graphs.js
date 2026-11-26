import { LitElement, css, html, nothing, svg } from 'https://unpkg.com/lit@3.3.3/index.js?module';

export function sgToPlato(sg) {
  return -616.868 + 1111.14 * sg - 630.272 * sg * sg + 135.997 * sg * sg * sg;
}

export function sgToBrix(sg) {
  return ((182.4601 * sg - 775.6821) * sg + 1262.7794) * sg - 669.5622;
}

export function renderFermentationGraphs(hass, batch, densityUnit) {
  const attrs = batch?.attributes;
  if (!attrs
      || String(attrs.status).toLowerCase() !== 'fermenting'
      || batch.state === 'unavailable' || batch.state === 'unknown'
      || !attrs.temperature_statistic_id || !attrs.specific_gravity_statistic_id) {
    return nothing;
  }
  return html`<grainfather-fermentation-graphs
    .hass=${hass}
    .temperatureId=${attrs.temperature_statistic_id}
    .gravityId=${attrs.specific_gravity_statistic_id}
    .startTime=${attrs.fermentation_start_date}
    .hour=${Math.floor(Date.now() / 3600000)}
    .densityUnit=${densityUnit}
  ></grainfather-fermentation-graphs>`;
}

class GrainfatherFermentationGraphs extends LitElement {
  static properties = {
    hass: { attribute: false },
    temperatureId: { attribute: false },
    gravityId: { attribute: false },
    startTime: { attribute: false },
    hour: { attribute: false },
    densityUnit: { attribute: false },
    _result: { state: true },
  };

  static styles = css`
    :host { display: grid; gap: 8px; }
    .graph-panel { padding: 8px 10px; background: rgba(0,0,0,.20); border-radius: 10px; }
    .graph-title { color: #8fa0b4; font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; }
    .graph-empty { color: #8fa0b4; font-size: .8rem; min-height: 48px; display: grid; place-items: center; }
    .graph-svg { display: block; width: 100%; height: auto; margin-top: 4px; }
    .graph-label { fill: #8fa0b4; font-size: 22px; }
  `;

  willUpdate() {
    const startTime = Number.isFinite(Date.parse(this.startTime))
      ? this.startTime : '2001-01-07T00:00:00.000Z';
    const key = `${this.temperatureId}|${this.gravityId}|${startTime}|${this.hour}`;
    if (this._request?.key === key) return;

    const request = { key };
    this._request = request;
    this._result = undefined;
    this._load(request, startTime);
  }

  async _load(request, startTime) {
    try {
      const data = await this.hass.callWS({
        type: 'recorder/statistics_during_period',
        start_time: startTime,
        end_time: new Date().toISOString(),
        statistic_ids: [this.temperatureId, this.gravityId],
        period: 'hour',
        types: ['mean'],
      });
      if (this._request === request) this._result = data;
    } catch {
      if (this._request === request) this._result = null;
    }
  }

  _renderGraph(title, id, color, unit, precision = 1, convert = Number) {
    const values = (this._result?.[id] || []).filter(
      ({ mean }) => mean != null && mean !== '' && Number.isFinite(Number(mean)),
    );
    if (!values.length) {
      const message = this._result === undefined ? 'Loading history…'
        : this._result === null ? 'History unavailable' : 'No history yet';
      return html`<div class="graph-panel"><div class="graph-title">${title}</div><div class="graph-empty">${message}</div></div>`;
    }
    const numbers = values.map((row) => convert(Number(row.mean)));
    const min = Math.min(...numbers), max = Math.max(...numbers), range = max - min || 1;
    const points = numbers.map((value, index) => `${40 + index * 880 / Math.max(numbers.length - 1, 1)},${145 - (value - min) * 110 / range}`).join(' ');
    return html`<div class="graph-panel"><div class="graph-title">${title}</div>
      <svg class="graph-svg" viewBox="0 0 960 180" role="img" aria-label=${title}>
        ${numbers.length === 1
          ? svg`<circle cx="40" cy="145" r="5" fill=${color}></circle>`
          : svg`<polyline fill="none" stroke=${color} stroke-width="4" points=${points}></polyline>`}
        <text class="graph-label" x="40" y="175">${new Date(values[0].start).toLocaleDateString()}</text>
        <text class="graph-label" x="780" y="175">${new Date(values.at(-1).start).toLocaleDateString()}</text>
        <text class="graph-label" x="40" y="20">${max.toFixed(precision)} ${unit}</text>
        <text class="graph-label" x="820" y="20">${min.toFixed(precision)} ${unit}</text>
      </svg></div>`;
  }

  render() {
    const temperature = this._renderGraph('Temperature', this.temperatureId, '#d9c44a', '°C');
    const gravity = this.densityUnit === 'plato'
      ? this._renderGraph('Gravity', this.gravityId, '#7ec8e3', '°P', 1, sgToPlato)
      : this.densityUnit === 'brix'
        ? this._renderGraph('Gravity', this.gravityId, '#7ec8e3', '°Bx', 1, sgToBrix)
        : this._renderGraph('Gravity', this.gravityId, '#7ec8e3', 'SG', 4);
    return html`${temperature}${gravity}`;
  }
}

customElements.define('grainfather-fermentation-graphs', GrainfatherFermentationGraphs);
