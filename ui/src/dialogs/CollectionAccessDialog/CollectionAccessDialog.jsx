import React, { Component, PureComponent } from 'react';
import {
  Button,
  Classes,
  Callout,
  Checkbox,
  InputGroup,
  Intent,
} from '@blueprintjs/core';
import { defineMessages, FormattedMessage, injectIntl } from 'react-intl';
import { compose } from 'redux';
import { connect } from 'react-redux';
import {
  updateCollectionPermissions,
  fetchCollectionPermissions,
} from 'actions';
import { selectCollectionPermissions, selectFeatureFlags } from 'selectors';
import { Role } from 'components/common';
import FormDialog from 'dialogs/common/FormDialog';
import { showSuccessToast, showWarningToast } from 'app/toast';

import './CollectionAccessDialog.scss';

// external collections are never writeable, but users holding write access can
// still manage their permissions ("shareable")
const canManagePermissions = (collection) =>
  !!collection && (collection.writeable || collection.shareable);

const messages = defineMessages({
  title: {
    id: 'collection.edit.access_title',
    defaultMessage: 'Access control',
  },
  save_success: {
    id: 'collection.edit.save_success',
    defaultMessage: 'Your changes are saved.',
  },
  cancel_button: {
    id: 'collection.edit.cancel_button',
    defaultMessage: 'Cancel',
  },
  save_button: {
    id: 'collection.edit.save_button',
    defaultMessage: 'Save changes',
  },
  email_placeholder: {
    id: 'collection.edit.email_placeholder',
    defaultMessage: 'E-mail address',
  },
  add_email: {
    id: 'collection.edit.add_email',
    defaultMessage: 'Add person by e-mail',
  },
  remove_email: {
    id: 'collection.edit.remove_email',
    defaultMessage: 'Remove',
  },
});

let nextEmailRowId = 0;
const newEmailRow = () => ({
  key: `email-${nextEmailRowId++}`,
  email: '',
  read: true,
  write: false,
});

class PermissionRow extends PureComponent {
  render() {
    const { permission, onToggle, showWrite } = this.props;
    return (
      <tr>
        <td>
          <Role.Label role={permission.role} long icon={false} />
        </td>
        <td className="other-rows">
          <Checkbox
            checked={permission.read}
            onClick={() => onToggle(permission, 'read')}
          />
        </td>
        {showWrite && (
          <td className="other-rows">
            <Checkbox
              checked={permission.write}
              onClick={() => onToggle(permission, 'write')}
            />
          </td>
        )}
        <td className="action-cell" />
      </tr>
    );
  }
}

class EmailRow extends PureComponent {
  render() {
    const { row, onChange, onRemove, showWrite, autoFocus, intl } = this.props;
    return (
      <tr className="email-row">
        <td>
          <InputGroup
            type="email"
            value={row.email}
            autoFocus={autoFocus}
            placeholder={intl.formatMessage(messages.email_placeholder)}
            onChange={(e) => onChange(row.key, 'email', e.target.value)}
            // the dialog is wrapped in a <form> without a submit handler, so
            // stop Enter from triggering a native (page-reloading) submit
            onKeyDown={(e) => e.key === 'Enter' && e.preventDefault()}
          />
        </td>
        <td className="other-rows">
          <Checkbox
            checked={row.read}
            onChange={() => onChange(row.key, 'read', !row.read)}
          />
        </td>
        {showWrite && (
          <td className="other-rows">
            <Checkbox
              checked={row.write}
              onChange={() => onChange(row.key, 'write', !row.write)}
            />
          </td>
        )}
        <td className="action-cell">
          <Button
            minimal
            small
            icon="trash"
            intent={Intent.DANGER}
            aria-label={intl.formatMessage(messages.remove_email)}
            title={intl.formatMessage(messages.remove_email)}
            onClick={() => onRemove(row.key)}
          />
        </td>
      </tr>
    );
  }
}

class CollectionAccessDialog extends Component {
  constructor(props) {
    super(props);
    this.state = {
      permissions: [],
      emailRows: [],
      blocking: false,
    };
    this.bodyRef = React.createRef();
    this.onAddRole = this.onAddRole.bind(this);
    this.onAddEmailRow = this.onAddEmailRow.bind(this);
    this.onChangeEmailRow = this.onChangeEmailRow.bind(this);
    this.onRemoveEmailRow = this.onRemoveEmailRow.bind(this);
    this.onToggle = this.onToggle.bind(this);
    this.onSubmit = this.onSubmit.bind(this);
  }

  componentDidMount() {
    this.fetchPermissions();
  }

  componentDidUpdate(prevProps) {
    const { collection, permissions } = this.props;
    if (
      prevProps.collection &&
      collection.id !== undefined &&
      prevProps.collection.id !== collection.id
    ) {
      this.fetchPermissions();
    }
    if (!this.state.permissions.length && permissions.results) {
      this.setPermissions(permissions.results, false);
    }
  }

  onAddRole(role) {
    this.setState(({ permissions }) => ({
      permissions: [...permissions, { role, read: true, write: false }],
    }));
  }

  onAddEmailRow() {
    this.setState(
      ({ emailRows }) => ({ emailRows: [...emailRows, newEmailRow()] }),
      () => {
        const body = this.bodyRef.current;
        if (body) body.scrollTo({ top: body.scrollHeight, behavior: 'smooth' });
      }
    );
  }

  onChangeEmailRow(key, field, value) {
    this.setState(({ emailRows }) => ({
      emailRows: emailRows.map((row) =>
        row.key === key ? { ...row, [field]: value } : row
      ),
    }));
  }

  onRemoveEmailRow(key) {
    this.setState(({ emailRows }) => ({
      emailRows: emailRows.filter((row) => row.key !== key),
    }));
  }

  onToggle(permission, flag) {
    this.setState(({ permissions }) => ({
      permissions: permissions.map((perm) => ({
        ...perm,
        [flag]: perm.role.id === permission.role.id ? !perm[flag] : perm[flag],
      })),
    }));
  }

  async onSubmit() {
    const { intl, collection } = this.props;
    const { permissions, emailRows, blocking } = this.state;
    if (blocking) return;

    const emailPermissions = emailRows
      .map(({ email, read, write }) => ({ email: email.trim(), read, write }))
      .filter(({ email }) => email.length > 0);

    this.setState({ blocking: true });
    try {
      await this.props.updateCollectionPermissions(collection.id, [
        ...permissions,
        ...emailPermissions,
      ]);
      this.setState({ emailRows: [] });
      this.props.toggleDialog();
      showSuccessToast(intl.formatMessage(messages.save_success));
    } catch (e) {
      showWarningToast(e.message);
    }
    this.setState({ blocking: false });
  }

  setPermissions(permissions, blocking) {
    this.setState((state) => ({
      permissions: permissions || state.permissions,
      blocking: blocking === undefined ? state.blocking : blocking,
    }));
  }

  fetchPermissions() {
    const { collection } = this.props;
    this.setPermissions([], true);
    if (canManagePermissions(collection)) {
      this.props.fetchCollectionPermissions(collection.id);
    }
  }

  filterPermissions(type) {
    const { permissions } = this.state;
    return permissions.filter((perm) => perm.role.type === type);
  }

  render() {
    const { collection, shareSuggestRoles, intl } = this.props;
    const { permissions, emailRows, blocking } = this.state;

    if (!canManagePermissions(collection) || !permissions) {
      return null;
    }

    // write access can't be granted on external collections, so the column is
    // only shown for collections the current user can actually edit
    const showWrite = !!collection.writeable;
    const colSpan = showWrite ? '4' : '3';
    const exclude = permissions.map((perm) => perm.role.id);
    const systemRoles = this.filterPermissions('system');
    const groupRoles = this.filterPermissions('group');
    const userRoles = this.filterPermissions('user');
    return (
      <FormDialog
        processing={blocking}
        icon="key"
        className="CollectionAccessDialog"
        isOpen={this.props.isOpen}
        onClose={this.props.toggleDialog}
        title={intl.formatMessage(messages.title)}
        enforceFocus={false}
      >
        <div
          className={`${Classes.DIALOG_BODY} CollectionAccessDialog__body`}
          ref={this.bodyRef}
        >
          <div className="CollectionPermissions">
            <table className="settings-table">
              <thead>
                <tr key={0}>
                  <th />
                  <th>
                    <FormattedMessage
                      id="collection.edit.permissionstable.view"
                      defaultMessage="View"
                    />
                  </th>
                  {showWrite && (
                    <th>
                      <FormattedMessage
                        id="collection.edit.permissionstable.edit"
                        defaultMessage="Edit"
                      />
                    </th>
                  )}
                  <th className="action-cell" />
                </tr>
              </thead>
              <tbody>
                {systemRoles.map((permission) => (
                  <PermissionRow
                    key={permission.role.id}
                    permission={permission}
                    onToggle={this.onToggle}
                    showWrite={showWrite}
                  />
                ))}
                {groupRoles.length > 0 && (
                  <>
                    <tr key="groups">
                      <td className="header-topic" colSpan={colSpan}>
                        <FormattedMessage
                          id="collection.edit.groups"
                          defaultMessage="Groups"
                        />
                      </td>
                    </tr>
                    {groupRoles.map((permission) => (
                      <PermissionRow
                        key={permission.role.id}
                        permission={permission}
                        onToggle={this.onToggle}
                        showWrite={showWrite}
                      />
                    ))}
                  </>
                )}
                <tr key="users">
                  <td className="header-topic" colSpan={colSpan}>
                    <FormattedMessage
                      id="collection.edit.users"
                      defaultMessage="Users"
                    />
                  </td>
                </tr>
                {userRoles.map((permission) => (
                  <PermissionRow
                    key={permission.role.id}
                    permission={permission}
                    onToggle={this.onToggle}
                    showWrite={showWrite}
                  />
                ))}
                {emailRows.map((row, index) => (
                  <EmailRow
                    key={row.key}
                    row={row}
                    intl={intl}
                    showWrite={showWrite}
                    autoFocus={index === emailRows.length - 1}
                    onChange={this.onChangeEmailRow}
                    onRemove={this.onRemoveEmailRow}
                  />
                ))}
                <tr key="add">
                  <td colSpan={colSpan}>
                    {shareSuggestRoles ? (
                      <Role.Select
                        onSelect={this.onAddRole}
                        exclude={exclude}
                      />
                    ) : (
                      <Button
                        icon="plus"
                        onClick={this.onAddEmailRow}
                        disabled={blocking}
                        text={intl.formatMessage(messages.add_email)}
                      />
                    )}
                    <Callout intent={Intent.WARNING}>
                      <FormattedMessage
                        id="collection.edit.permissions_warning"
                        defaultMessage="Note: User must already have an Aleph account in order to receive access."
                      />
                    </Callout>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div className={Classes.DIALOG_FOOTER}>
          <div className={Classes.DIALOG_FOOTER_ACTIONS}>
            <Button
              onClick={this.props.toggleDialog}
              disabled={blocking}
              text={intl.formatMessage(messages.cancel_button)}
            />
            <Button
              type="button"
              onClick={this.onSubmit}
              intent={Intent.PRIMARY}
              disabled={blocking}
              text={intl.formatMessage(messages.save_button)}
            />
          </div>
        </div>
      </FormDialog>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const collectionId = ownProps.collection.id;
  return {
    permissions: selectCollectionPermissions(state, collectionId),
    shareSuggestRoles: !!selectFeatureFlags(state)?.share_suggest_roles,
  };
};
const mapDispatchToProps = {
  updateCollectionPermissions,
  fetchCollectionPermissions,
};

export default compose(
  connect(mapStateToProps, mapDispatchToProps),
  injectIntl
)(CollectionAccessDialog);
