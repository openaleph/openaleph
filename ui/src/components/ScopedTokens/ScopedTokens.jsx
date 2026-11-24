import React, { useCallback, useEffect, useState } from 'react';
import { defineMessages, FormattedMessage, useIntl } from 'react-intl';
import {
  Alert,
  Button,
  Callout,
  Checkbox,
  FormGroup,
  HTMLSelect,
  HTMLTable,
  InputGroup,
  Intent,
  MenuItem,
} from '@blueprintjs/core';
import { Suggest } from '@blueprintjs/select';

import { endpoint } from 'app/api';
import { showResponseToast, showSuccessToast } from 'app/toast';
import ClipboardInput from 'components/common/ClipboardInput';

import './ScopedTokens.scss';

const HOUR = 60 * 60;
const DAY = 24 * HOUR;
const LIFETIMES = [HOUR, DAY, 7 * DAY, 30 * DAY];
const DEFAULT_LIFETIME = DAY;
const MAX_COLLECTIONS = 100;

const messages = defineMessages({
  label: {
    id: 'settings.tokens.label',
    defaultMessage: 'What is this token for?',
  },
  label_placeholder: {
    id: 'settings.tokens.label.placeholder',
    defaultMessage: 'e.g. Nightly import job',
  },
  collections: {
    id: 'settings.tokens.collections',
    defaultMessage: 'Datasets and investigations it may access',
  },
  collections_placeholder: {
    id: 'settings.tokens.collections.placeholder',
    defaultMessage: 'Search by name…',
  },
  collections_empty: {
    id: 'settings.tokens.collections.empty',
    defaultMessage: 'No matching datasets or investigations',
  },
  write: {
    id: 'settings.tokens.write',
    defaultMessage: 'May write',
  },
  remove: {
    id: 'settings.tokens.remove',
    defaultMessage: 'Remove',
  },
  lifetime: {
    id: 'settings.tokens.lifetime',
    defaultMessage: 'Expires after',
  },
  lifetime_hours: {
    id: 'settings.tokens.lifetime.hours',
    defaultMessage: '{count, plural, one {# hour} other {# hours}}',
  },
  lifetime_days: {
    id: 'settings.tokens.lifetime.days',
    defaultMessage: '{count, plural, one {# day} other {# days}}',
  },
  create: {
    id: 'settings.tokens.create',
    defaultMessage: 'Create token',
  },
  revoke: {
    id: 'settings.tokens.revoke',
    defaultMessage: 'Revoke',
  },
  revoke_cancel: {
    id: 'settings.tokens.revoke.cancel',
    defaultMessage: 'Cancel',
  },
  revoked: {
    id: 'settings.tokens.revoked',
    defaultMessage: 'The token has been revoked.',
  },
  access_summary: {
    id: 'settings.tokens.access.summary',
    defaultMessage:
      '{read, plural, one {# collection} other {# collections}}, {write, plural, =0 {read only} other {# writable}}',
  },
  dismiss: {
    id: 'settings.tokens.created.dismiss',
    defaultMessage: 'I have copied it',
  },
});

function getLifetimes(maxExpire) {
  const lifetimes = LIFETIMES.filter((seconds) => seconds <= maxExpire);
  if (!lifetimes.length || lifetimes[lifetimes.length - 1] < maxExpire) {
    // Always offer the longest lifetime this instance allows.
    lifetimes.push(maxExpire);
  }
  return lifetimes;
}

function formatLifetime(intl, seconds) {
  if (seconds % DAY === 0) {
    return intl.formatMessage(messages.lifetime_days, { count: seconds / DAY });
  }
  return intl.formatMessage(messages.lifetime_hours, {
    count: Math.max(1, Math.round(seconds / HOUR)),
  });
}

function TokenList({ tokens, onRevoke }) {
  const intl = useIntl();
  if (!tokens.length) {
    return (
      <p className="ScopedTokens__empty">
        <FormattedMessage
          id="settings.tokens.empty"
          defaultMessage="You have no scoped tokens."
        />
      </p>
    );
  }
  return (
    <HTMLTable className="ScopedTokens__list" striped>
      <thead>
        <tr>
          <th>
            <FormattedMessage
              id="settings.tokens.list.label"
              defaultMessage="Token"
            />
          </th>
          <th>
            <FormattedMessage
              id="settings.tokens.list.access"
              defaultMessage="Access"
            />
          </th>
          <th>
            <FormattedMessage
              id="settings.tokens.list.expires"
              defaultMessage="Expires"
            />
          </th>
          <th />
        </tr>
      </thead>
      <tbody>
        {tokens.map((token) => (
          <tr key={token.id}>
            <td>{token.label}</td>
            <td>
              {intl.formatMessage(messages.access_summary, {
                read: token.read.length,
                write: token.write.length,
              })}
            </td>
            <td>
              <time dateTime={token.expires_at}>
                {intl.formatDate(token.expires_at, {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </time>
            </td>
            <td className="ScopedTokens__list__actions">
              <Button
                small
                minimal
                icon="trash"
                intent={Intent.DANGER}
                onClick={() => onRevoke(token)}
                text={intl.formatMessage(messages.revoke)}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </HTMLTable>
  );
}

function CollectionPicker({ selected, onSelect }) {
  const intl = useIntl();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);

  useEffect(() => {
    let current = true;
    // Drop the previous results so that Enter cannot pick a stale one.
    setItems([]);
    const params = { limit: 10 };
    if (query.trim().length) {
      params.prefix = query.trim();
    }
    endpoint
      .get('collections', { params })
      .then((response) => current && setItems(response.data.results || []))
      .catch(() => current && setItems([]));
    return () => {
      current = false;
    };
  }, [query]);

  const selectedIds = selected.map((collection) => collection.id);
  return (
    <Suggest
      items={items.filter((item) => !selectedIds.includes(item.id))}
      query={query}
      onQueryChange={setQuery}
      selectedItem={null}
      inputValueRenderer={() => ''}
      itemRenderer={(item, { handleClick, modifiers }) => (
        <MenuItem
          key={item.id}
          active={modifiers.active}
          icon={item.casefile ? 'briefcase' : 'database'}
          text={item.label}
          onClick={handleClick}
        />
      )}
      onItemSelect={(item) => {
        onSelect(item);
        setQuery('');
      }}
      noResults={
        <MenuItem
          disabled
          text={intl.formatMessage(messages.collections_empty)}
        />
      }
      resetOnSelect
      // Stay in the field so that several can be picked in a row.
      closeOnSelect={false}
      disabled={selected.length >= MAX_COLLECTIONS}
      inputProps={{
        id: 'scoped-token-collections',
        leftIcon: 'search',
        placeholder: intl.formatMessage(messages.collections_placeholder),
        // Enter picks a suggestion; it must not submit the token form.
        onKeyDown: (event) => event.key === 'Enter' && event.preventDefault(),
      }}
      popoverProps={{ minimal: true, matchTargetWidth: true }}
      fill
    />
  );
}

export default function ScopedTokens({ maxExpire }) {
  const intl = useIntl();
  const lifetimes = getLifetimes(maxExpire);
  const [tokens, setTokens] = useState([]);
  const [label, setLabel] = useState('');
  const [selected, setSelected] = useState([]);
  const [writable, setWritable] = useState([]);
  const [lifetime, setLifetime] = useState(
    lifetimes.includes(DEFAULT_LIFETIME) ? DEFAULT_LIFETIME : lifetimes[0]
  );
  const [created, setCreated] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const [busy, setBusy] = useState(false);

  const fetchTokens = useCallback(async () => {
    try {
      const response = await endpoint.get('tokens');
      setTokens(response.data.results || []);
    } catch (error) {
      showResponseToast(error.response, intl);
    }
  }, [intl]);

  useEffect(() => {
    fetchTokens();
  }, [fetchTokens]);

  const onSelect = (collection) => {
    setSelected([...selected, collection]);
  };

  const onRemove = (collection) => {
    setSelected(selected.filter((item) => item.id !== collection.id));
    setWritable(writable.filter((id) => id !== collection.id));
  };

  const onToggleWrite = (collection) => {
    if (writable.includes(collection.id)) {
      setWritable(writable.filter((id) => id !== collection.id));
    } else {
      setWritable([...writable, collection.id]);
    }
  };

  const valid = label.trim().length > 0 && selected.length > 0;

  const onCreate = async (event) => {
    event.preventDefault();
    if (!valid || busy) {
      return;
    }
    setBusy(true);
    try {
      const response = await endpoint.post('tokens', {
        label: label.trim(),
        read: selected.map((collection) => parseInt(collection.id, 10)),
        write: writable.map((id) => parseInt(id, 10)),
        expires_in: lifetime,
      });
      setCreated(response.data);
      setLabel('');
      setSelected([]);
      setWritable([]);
      await fetchTokens();
    } catch (error) {
      showResponseToast(error.response, intl);
    }
    setBusy(false);
  };

  const onRevoke = async () => {
    const token = revoking;
    setRevoking(null);
    try {
      await endpoint.delete(`tokens/${token.id}`);
      if (created && created.id === token.id) {
        setCreated(null);
      }
      showSuccessToast(intl.formatMessage(messages.revoked));
    } catch (error) {
      showResponseToast(error.response, intl);
    }
    await fetchTokens();
  };

  return (
    <div className="ScopedTokens">
      <h3>
        <FormattedMessage
          id="settings.tokens.title"
          defaultMessage="Scoped API tokens"
        />
      </h3>
      <p className="ScopedTokens__help">
        <FormattedMessage
          id="settings.tokens.help"
          defaultMessage="Your API key can do everything you can and never expires. For scripts and integrations, create a token instead: it only works for the datasets and investigations you choose, and only for a limited time. It cannot change your account, sharing settings or other tokens."
        />
      </p>

      {created && (
        <Callout
          className="ScopedTokens__created"
          intent={Intent.SUCCESS}
          icon="key"
          title={created.label}
        >
          <p>
            <FormattedMessage
              id="settings.tokens.created.help"
              defaultMessage="Copy this token now. It will not be shown again."
            />
          </p>
          <ClipboardInput
            id="scoped-token-secret"
            icon="key"
            value={created.token}
          />
          <p className="ScopedTokens__created__usage">
            <FormattedMessage
              id="settings.tokens.created.usage"
              defaultMessage="Send it in the {header} header, like an API key. It is not accepted in a URL."
              values={{ header: <code>Authorization</code> }}
            />
          </p>
          <Button
            small
            onClick={() => setCreated(null)}
            text={intl.formatMessage(messages.dismiss)}
          />
        </Callout>
      )}

      <TokenList tokens={tokens} onRevoke={setRevoking} />

      <form className="ScopedTokens__form" onSubmit={onCreate}>
        <h4>
          <FormattedMessage
            id="settings.tokens.new"
            defaultMessage="Create a new token"
          />
        </h4>
        <FormGroup
          label={intl.formatMessage(messages.label)}
          labelFor="scoped-token-label"
        >
          <InputGroup
            id="scoped-token-label"
            value={label}
            maxLength={100}
            placeholder={intl.formatMessage(messages.label_placeholder)}
            onChange={(event) => setLabel(event.target.value)}
          />
        </FormGroup>
        <FormGroup
          label={intl.formatMessage(messages.collections)}
          labelFor="scoped-token-collections"
        >
          <CollectionPicker selected={selected} onSelect={onSelect} />
          {selected.length > 0 && (
            <ul className="ScopedTokens__selected">
              {selected.map((collection) => (
                <li key={collection.id}>
                  <span className="ScopedTokens__selected__label">
                    {collection.label}
                  </span>
                  <Checkbox
                    inline
                    checked={writable.includes(collection.id)}
                    disabled={!collection.writeable}
                    onChange={() => onToggleWrite(collection)}
                    label={intl.formatMessage(messages.write)}
                  />
                  <Button
                    small
                    minimal
                    icon="cross"
                    aria-label={intl.formatMessage(messages.remove)}
                    onClick={() => onRemove(collection)}
                  />
                </li>
              ))}
            </ul>
          )}
        </FormGroup>
        <FormGroup
          label={intl.formatMessage(messages.lifetime)}
          labelFor="scoped-token-lifetime"
        >
          <HTMLSelect
            id="scoped-token-lifetime"
            value={lifetime}
            onChange={(event) =>
              setLifetime(parseInt(event.currentTarget.value, 10))
            }
            options={lifetimes.map((seconds) => ({
              value: seconds,
              label: formatLifetime(intl, seconds),
            }))}
          />
        </FormGroup>
        <Button
          type="submit"
          icon="key"
          intent={Intent.PRIMARY}
          disabled={!valid || busy}
          loading={busy}
          text={intl.formatMessage(messages.create)}
        />
      </form>

      <Alert
        isOpen={revoking !== null}
        icon="trash"
        intent={Intent.DANGER}
        cancelButtonText={intl.formatMessage(messages.revoke_cancel)}
        confirmButtonText={intl.formatMessage(messages.revoke)}
        onCancel={() => setRevoking(null)}
        onConfirm={onRevoke}
      >
        <FormattedMessage
          id="settings.tokens.revoke.confirm"
          defaultMessage="Revoke the token “{label}”? Anything still using it will stop working at once."
          values={{ label: revoking ? revoking.label : '' }}
        />
      </Alert>
    </div>
  );
}
