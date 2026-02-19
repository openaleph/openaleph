import React from 'react';
import { Classes } from '@blueprintjs/core';
import { Schema as FTMSchema, IconRegistry } from '@alephdata/followthemoney';
import c from 'classnames';
import './Schema.scss';

interface ISchemaCommonProps {
  schema: FTMSchema;
  className?: string;
  size?: number;
}

class SchemaIcon extends React.Component<ISchemaCommonProps> {
  render() {
    const { className, schema, size = 16 } = this.props;
    const iconPaths = IconRegistry.getSchemaIcon(schema);
    return (
      <span className={c('SchemaIcon', Classes.ICON, className)}>
        <svg viewBox={'0 0 25 25'} height={size} width={size}>
          {iconPaths.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </svg>
      </span>
    );
  }
}

interface ISchemaLabelProps extends ISchemaCommonProps {
  plural?: boolean;
  icon?: boolean;
  neutral?: boolean;
}

function getSchemaColorClass(schema: FTMSchema): string {
  if (schema.isA('Person')) return 'SchemaLabel--person';
  if (schema.isA('Organization')) return 'SchemaLabel--organization';
  if (schema.isDocument()) return 'SchemaLabel--document';
  if (schema.isA('Event')) return 'SchemaLabel--event';
  return 'SchemaLabel--default';
}

class SchemaLabel extends React.Component<ISchemaLabelProps> {
  render() {
    const { schema, plural = false, icon, neutral } = this.props;
    const label = plural ? schema.plural : schema.label;
    if (icon) {
      const colorClass = neutral ? 'SchemaLabel--neutral' : getSchemaColorClass(schema);
      return (
        <span className={c('SchemaLabel', colorClass)}>
          <Schema.Icon schema={schema} className="left-icon" />
          {label}
        </span>
      );
    }
    return label;
  }
}

class Schema extends React.Component {
  static Label = SchemaLabel;

  static Icon = SchemaIcon;
}

export default Schema;
