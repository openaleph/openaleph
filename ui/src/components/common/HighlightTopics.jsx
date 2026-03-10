import React, { Component } from 'react';
import { Link } from 'react-router-dom';
import queryString from 'query-string';
import ReactMarkdown from 'react-markdown';

import { Country } from 'components/common';
import CollectionList from './CollectionList';

class HighlightTopics extends Component {
  constructor(props) {
    super(props);
    this.state = { topics: null, error: false };
  }

  componentDidMount() {
    this.fetchTopics();
  }

  componentDidUpdate(prevProps) {
    if (prevProps.url !== this.props.url) {
      this.fetchTopics();
    }
  }

  fetchTopics() {
    const { url } = this.props;
    if (!url) return;

    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then((data) => this.setState({ topics: data.topics || data }))
      .catch(() => this.setState({ error: true }));
  }

  renderTopic(topic, index) {
    return (
      <div key={index} className="oa-highlight-topic">
        {topic.countries && topic.countries.length > 0 && (
          <div className="oa-highlight-topic__countries">
            <Country.List codes={topic.countries} />
          </div>
        )}
        {topic.image && (
          <div className="oa-highlight-topic__image">
            <img
              src={topic.image.thumbnail_url || topic.image.url}
              alt={(topic.image.alt && topic.image.alt[0]?.text) || topic.title}
            />
            {topic.image.attribution && (
              <span className="oa-highlight-topic__attribution">
                <span className="oa-highlight-topic__attribution__license">
                  {topic.image.attribution.license_url ? (
                    <a href={topic.image.attribution.license_url}>
                      {topic.image.attribution.license}
                    </a>
                  ) : (
                    topic.image.attribution.license
                  )}
                </span>
                {topic.image.attribution.author && (
                  <span className="oa-highlight-topic__attribution__author">
                    {' '}
                    {topic.image.attribution.author}
                  </span>
                )}
                {topic.image.attribution.source && (
                  <span className="oa-highlight-topic__attribution__source">
                    {' / '}
                    {topic.image.attribution.source_url ? (
                      <a href={topic.image.attribution.source_url}>
                        {topic.image.attribution.source}
                      </a>
                    ) : (
                      topic.image.attribution.source
                    )}
                  </span>
                )}
              </span>
            )}
          </div>
        )}
        <div className="oa-highlight-topic__content">
          <h4 className="oa-highlight-topic__title">{topic.title}</h4>
          {topic.description && (
            <div className="oa-highlight-topic__description">
              <ReactMarkdown>{topic.description}</ReactMarkdown>
            </div>
          )}
          {topic.search_terms && topic.search_terms.length > 0 && (
            <div className="oa-highlight-topic__terms">
              {topic.search_terms.map((term) => (
                <Link
                  key={term}
                  to={{
                    pathname: '/search',
                    search: queryString.stringify({ q: `"${term}"` }),
                  }}
                  className="oa-highlight-topic__term"
                >
                  {term}
                </Link>
              ))}
            </div>
          )}
          {topic.collections && topic.collections.length > 0 && (
            <CollectionList ids={topic.collections} dark />
          )}
        </div>
      </div>
    );
  }

  render() {
    const { topics, error } = this.state;
    if (error || !topics) return null;

    return (
      <div className="oa-highlight-topics">
        {topics.map((topic, i) => this.renderTopic(topic, i))}
      </div>
    );
  }
}

export default HighlightTopics;
