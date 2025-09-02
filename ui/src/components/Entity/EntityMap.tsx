import Map, { Marker } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import * as _ from 'lodash';

import { Entity } from '@alephdata/followthemoney';

// Make lodash available globally for MapLibre GL JS
(window as any)._ = _;

interface IComponent {
  readonly entity: Entity;
  readonly marker?: boolean;
  readonly width?: number | string;
  readonly height?: number | string;
}

export default function EntityMap(props: IComponent) {
  const [lon, lat] = [
    props.entity.getFirst('longitude'),
    props.entity.getFirst('latitude'),
  ];
  if (!lon || !lat) return null;
  const longitude = parseFloat(lon.toString());
  const latitude = parseFloat(lat.toString());
  const { width = '100%', height = 400 } = props;
  return (
    <div className="EntityMap">
      <Map
        initialViewState={{
          longitude,
          latitude,
          zoom: 14,
        }}
        style={{ width, height }}
        mapStyle="https://tiles.versatiles.org/assets/styles/colorful/style.json"
      >
        {props.marker && (
          <Marker longitude={longitude} latitude={latitude} anchor="bottom">
            <img
              src="/static/mapMarker.png"
              alt={props.entity.getCaption()}
              width={50}
            />
          </Marker>
        )}
      </Map>
    </div>
  );
}
