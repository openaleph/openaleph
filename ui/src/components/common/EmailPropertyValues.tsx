import { Entity as FTMEntity } from '@alephdata/followthemoney';
import { Property, Entity, Schema } from 'components/common';
import wordList from 'util/wordList';
import { RE_ENCODED_HEADER } from 'util/isBase64Encoded';

type EmailPropertyValuesProps = {
  entity: FTMEntity;
  prop: string;
  entityProp?: string;
  separator?: string;
  preview?: boolean;
};

// Fallback mapping when the caller doesn't pass `entityProp` explicitly
// (e.g. EntityReferencesMode rows, where we only know the header prop).
const ENTITY_PROPS: Record<string, string> = {
  from: 'emitters',
  to: 'recipients',
  cc: 'recipients',
  bcc: 'recipients',
};

export default function EmailPropertyValues({
  entity,
  prop,
  entityProp,
  separator = ' · ',
  preview = false,
}: EmailPropertyValuesProps) {
  const propObj = entity.schema.getProperty(prop);
  const resolvedEntityProp = entityProp ?? ENTITY_PROPS[prop];

  const values = entity.getProperty(prop).filter((value) => {
    // Drop raw MIME-encoded header strings (e.g. `=?utf-8?B?…?=`) that
    // never got decoded upstream — rendering them verbatim is noise.
    // Entity values pass through untouched.
    return typeof value !== 'string' || !RE_ENCODED_HEADER.test(value);
  });
  const entityValues = resolvedEntityProp
    ? entity.getProperty(resolvedEntityProp)
    : [];

  const formattedValues = values
    .map((value) => {
      const key = value instanceof FTMEntity ? value.id : value;
      const formattedValue = (
        <Property.Value
          key={key}
          entity={entity}
          prop={propObj}
          value={value}
          showTime={true}
        />
      );

      if (typeof value !== 'string') {
        return formattedValue;
      }

      const normValue = value.toLowerCase().trim();

      for (const entityValue of entityValues) {
        if (!(entityValue instanceof FTMEntity)) {
          continue;
        }

        if (!entityValue?.id) {
          continue;
        }

        for (const email of entityValue.getProperty('email')) {
          if (typeof email !== 'string') {
            continue;
          }

          const normEmail = email.toLowerCase().trim();

          if (normValue.includes(normEmail)) {
            return (
              <Entity.Link
                key={entityValue.id}
                entity={entityValue}
                icon
                preview={preview}
              >
                <Schema.Icon
                  schema={entityValue.schema}
                  className="left-icon"
                  size={16}
                />
                {entityValue.getCaption() === email ? (
                  email
                ) : (
                  `${entityValue.getCaption()} <${email}>`
                )}
              </Entity.Link>
            );
          }
        }
      }

      return formattedValue;
    })
    .filter(Boolean);

  return wordList(formattedValues, separator);
};
