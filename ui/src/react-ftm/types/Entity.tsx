import React from 'react';
import { Entity as FTMEntity } from '@alephdata/followthemoney';
import truncateText from 'truncate';
import c from 'classnames';
import Schema from './Schema';
import Transliterate from './Transliterate';
import { Classes } from '@blueprintjs/core';
import { RE_ENCODED_HEADER } from 'util/isBase64Encoded';


export interface FTMEntityExtended extends FTMEntity {
  caption?: string;
  latinized?: any;
}

interface IEntityLabelProps {
  entity: FTMEntityExtended;
  icon?: boolean;
  iconSize?: number;
  truncate?: number;
  className?: string;
  transliterate?: boolean;
}

class EntityLabel extends React.Component<IEntityLabelProps> {
  render() {
    const {
      entity,
      icon = false,
      iconSize = 16,
      truncate,
      className,
      transliterate = true,
    } = this.props;
    if (!entity || !entity.id || !FTMEntity.isEntity(entity)) {
      return null;
    }

    let caption = entity.caption || entity.getCaption();
    const match = caption.match(RE_ENCODED_HEADER);

    if (match) {
      const [, charset, encoding, encodedText] = match;

      // Base64 decoding
      if (encoding.toUpperCase() === "B") {

        const binaryStr = atob(encodedText);
        const bytes = Uint8Array.from(binaryStr, (c) => c.charCodeAt(0));
        caption = new TextDecoder(charset).decode(bytes);
      }

      // Quoted-Printable decoding
      if (encoding.toUpperCase() === "Q") {
        const qpDecoded = encodedText
          .replace(/_/g, " ")
          .replace(/=([A-Fa-f0-9]{2})/g, (_, hex) =>
            String.fromCharCode(parseInt(hex, 16))
          );
        const bytes = Uint8Array.from(qpDecoded, (c) => c.charCodeAt(0));
        caption = new TextDecoder(charset).decode(bytes);
      }
    }

    caption = caption ? caption : entity.schema.name;

    const label = truncate ? truncateText(caption, truncate) : caption;
    return (
      <span
        className={c('EntityLabel', !label && Classes.TEXT_MUTED, className)}
        title={caption}
      >
        {icon && (
          <Schema.Icon
            schema={entity.schema}
            className="left-icon"
            size={iconSize}
          />
        )}
        <span>
          <Transliterate
            value={label}
            lookup={transliterate && entity.latinized}
          />
        </span>
      </span>
    );
  }
}

class Entity extends React.Component {
  static Label = EntityLabel;
}

export default Entity;
