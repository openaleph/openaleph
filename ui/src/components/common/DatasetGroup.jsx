import React from 'react';
import ReactMarkdown from 'react-markdown';
import CollectionList from './CollectionList';

import './DatasetGroup.scss';

function DatasetGroup({ label, description, icon, collections, body, content }) {
  let bodyHtml = null;
  if (body) {
    try {
      bodyHtml = decodeURIComponent(escape(atob(body)));
    } catch (e) {
      bodyHtml = null;
    }
  }

  return (
    <div className="DatasetGroup">
      <div className="DatasetGroup__header">
        {icon && (
          <div className="DatasetGroup__icon">
            <img src={icon.startsWith('http') ? icon : `/static/${icon}`} alt="" />
          </div>
        )}
        <div className="DatasetGroup__meta">
          <h3 className="DatasetGroup__label">{label}</h3>
          {description && (
            <p className="DatasetGroup__description">{description}</p>
          )}
        </div>
      </div>
      {bodyHtml && (
        <div
          className="DatasetGroup__body"
          dangerouslySetInnerHTML={{ __html: bodyHtml }}
        />
      )}
      {content && (
        <div className="DatasetGroup__body">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      )}
      <CollectionList ids={collections} />
    </div>
  );
}

export default DatasetGroup;
