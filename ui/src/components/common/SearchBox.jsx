import React, { PureComponent } from 'react';
import { defineMessages, injectIntl } from 'react-intl';
import { InputGroup, Switch } from '@blueprintjs/core';
import c from 'classnames';

import './SearchBox.scss';

const messages = defineMessages({
  placeholder: {
    id: 'search.placeholder_default',
    defaultMessage: 'Search…',
  },
  placeholder_label: {
    id: 'search.placeholder_label',
    defaultMessage: 'Search in {label}',
  },
  synonyms_toggle: {
    id: 'search.synonyms_toggle',
    defaultMessage: 'Include synonyms',
  },
});

export class SearchBox extends PureComponent {
  constructor(props) {
    super(props);
    this.state = {};
    this.onQueryTextChange = this.onQueryTextChange.bind(this);
    this.onSubmitSearch = this.onSubmitSearch.bind(this);
    this.onSynonymsChange = this.onSynonymsChange.bind(this);
  }

  static getDerivedStateFromProps(nextProps, prevState) {
    const nextQueryText = nextProps.query
      ? nextProps.query.getString('q')
      : prevState.queryText;
    const nextSynonyms = nextProps.query
      ? nextProps.query.getBool('synonyms')
      : prevState.synonyms;
    const queryChanged =
      !prevState?.prevQuery ||
      prevState.prevQuery.getString('q') !== nextQueryText;
    const synonymsChanged =
      !prevState?.prevQuery ||
      prevState.prevQuery.getBool('synonyms') !== nextSynonyms;
    return {
      prevQuery: nextProps.query,
      queryText: queryChanged ? nextQueryText : prevState.queryText,
      synonyms: synonymsChanged ? nextSynonyms : prevState.synonyms,
    };
  }

  onQueryTextChange(e) {
    const queryText = e.target.value;
    this.setState({ queryText });
  }

  onSynonymsChange() {
    const { onSynonymsChange } = this.props;
    const { synonyms } = this.state;
    const newValue = !synonyms;
    this.setState({ synonyms: newValue });
    if (onSynonymsChange) {
      onSynonymsChange(newValue);
    }
  }

  onSubmitSearch(event) {
    const { onSearch } = this.props;
    const { queryText } = this.state;
    event.preventDefault();
    if (onSearch) {
      onSearch(queryText);
    }
  }

  render() {
    const {
      intl,
      placeholder,
      placeholderLabel,
      className,
      inputProps,
      showSynonymsToggle,
      synonymsToggleLightLabel,
    } = this.props;
    const { queryText, synonyms } = this.state;
    if (!this.props.onSearch) {
      return null;
    }

    let searchPlaceholder = intl.formatMessage(messages.placeholder);
    if (placeholder) {
      searchPlaceholder = placeholder;
    } else if (placeholderLabel) {
      searchPlaceholder = intl.formatMessage(messages.placeholder_label, {
        label: placeholderLabel,
      });
    }

    return (
      <div className="SearchBox">
        <form onSubmit={this.onSubmitSearch} className={c('SearchBox__form', className)}>
          <InputGroup
            fill
            leftIcon="search"
            onChange={this.onQueryTextChange}
            placeholder={searchPlaceholder}
            value={queryText}
            {...inputProps}
          />
        </form>
        {showSynonymsToggle && (
          <Switch
            checked={synonyms}
            label={intl.formatMessage(messages.synonyms_toggle)}
            onChange={this.onSynonymsChange}
            className={c('SearchBox__synonyms-toggle', {
              'SearchBox__synonyms-toggle--light-label': synonymsToggleLightLabel,
            })}
          />
        )}
      </div>
    );
  }
}
export default injectIntl(SearchBox);
