import React, { PureComponent } from 'react';
import { FormattedMessage } from 'react-intl';
import { Classes, Pre } from '@blueprintjs/core';
import { Skeleton } from 'components/common';
import EmailPropertyValues from 'components/common/EmailPropertyValues';

import './EmailViewer.scss';

class EmailViewer extends PureComponent {
  headerProperty(name, entitiesProp) {
    const { document } = this.props;
    const prop = document.schema.getProperty(name);

    if (!document.hasProperty(name)) {
      return null;
    }

    return (
      <tr key={prop.qname}>
        <th>{prop.label}</th>
        <td>
          <EmailPropertyValues
            entity={document}
            prop={name}
            entityProp={entitiesProp}
            separator=", "
          />
        </td>
      </tr>
    );
  }

  renderHeaders() {
    const { document } = this.props;
    if (document.isPending) {
      return null;
    }
    return (
      <div className="email-header">
        <table className={Classes.HTML_TABLE}>
          <tbody>
            {this.headerProperty('from', 'emitters')}
            {this.headerProperty('date')}
            {this.headerProperty('subject')}
            {this.headerProperty('to', 'recipients')}
            {this.headerProperty('cc', 'recipients')}
            {this.headerProperty('bcc', 'recipients')}
            {this.headerProperty('inReplyToEmail')}
          </tbody>
        </table>
      </div>
    );
  }

  renderBody() {
    const { document } = this.props;

    if (document.isPending) {
      return <Skeleton.Text type="span" length={1000} />;
    }

    if (document.safeHtml && document.safeHtml.length) {
      return document.safeHtml.map((value, index) => (
        <div key={index} dangerouslySetInnerHTML={{ __html: value }} />
      ));
    }

    const bodyText = document.getFirst('bodyText');
    if (bodyText && bodyText.length > 0) {
      return <Pre>{bodyText}</Pre>;
    }

    return (
      <p className={Classes.TEXT_MUTED}>
        <FormattedMessage
          id="email.body.empty"
          defaultMessage="No message body."
        />
      </p>
    );
  }

  render() {
    const { dir } = this.props;
    return (
      <div className="outer">
        <div className="inner EmailViewer">
          {this.renderHeaders()}
          <div className="email-body" dir={dir}>
            {this.renderBody()}
          </div>
        </div>
      </div>
    );
  }
}

export default EmailViewer;
