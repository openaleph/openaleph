import { Entity as FTMEntity } from '@alephdata/followthemoney';
import { Property, Entity, Schema } from 'components/common';
import wordList from 'util/wordList';

type EmailPropertyValuesProps = {
  entity: FTMEntity;
  prop: string;
  separator?: string;
  preview?: boolean;
};

const ENTITY_PROPS: Record<string, string> = {
  from: 'emitters',
  to: 'recipients',
  cc: 'recipients',
  bcc: 'recipients',
};

export default function EmailPropertyValues({
  entity,
  prop,
  separator = ' · ',
  preview = false,
}: EmailPropertyValuesProps) {
  const propObj = entity.schema.getProperty(prop);
  const entityProp = ENTITY_PROPS[prop];

  const values = entity.getProperty(prop);
  const entityValues = entityProp ? entity.getProperty(entityProp) : [];

  const formattedValues = values
    .map((value) => {
      if (typeof value !== 'string') {
        return null;
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

      return (
        <Property.Value
          key={value}
          entity={entity}
          prop={propObj}
          value={value}
          showTime={true}
        />
      );
    })
    .filter(Boolean);

  return wordList(formattedValues, separator);
};
