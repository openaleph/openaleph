import React, { Component } from 'react';
import { FormattedMessage, injectIntl } from 'react-intl';
import { connect } from 'react-redux';

import withRouter from 'app/withRouter';
import { selectModel } from 'selectors';
import {
  JudgementButtons,
  Collection,
  EntityDecisionRow,
} from 'components/common';
import EntityCompare from 'components/Entity/EntityCompare';
import { pairwiseJudgement } from 'actions';
import { showWarningToast } from 'app/toast';

class ProfileItemsMode extends Component {
  constructor(props) {
    super(props);
    this.onDecide = this.onDecide.bind(this);
  }

  async onDecide(item) {
    try {
      await this.props.pairwiseJudgement({
        entity: item.entity,
        match: item.match,
        judgement: item.judgement,
      });
    } catch (e) {
      showWarningToast(e.message);
    }
  }

  renderRow(item, index) {
    const { canonical } = this.props;
    return (
      <EntityDecisionRow
        key={item.entity.id}
        selected={false}
      >
        <td className="numeric narrow">
          <JudgementButtons obj={item} onChange={this.onDecide} />
        </td>
        <td className="entity bordered">
          <EntityCompare
            entity={item.entity}
            other={canonical.entity}
          />
        </td>
        <td className="collection">
          <Collection.Link collection={item.entity?.collection} icon />
        </td>
      </EntityDecisionRow>
    );
  }

  render() {
    const { items } = this.props;

    return (
      <div className="ProfileItemsMode">
        <table className="data-table">
          <thead>
            <tr>
              <th className="numeric narrow" />
              <th>
                <span className="value">
                  <FormattedMessage
                    id="profile.items.entity"
                    defaultMessage="Combined entities"
                  />
                </span>
              </th>
              <th className="collection">
                <span className="value">
                  <FormattedMessage
                    id="xref.match_collection"
                    defaultMessage="Dataset"
                  />
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => this.renderRow(item, i))}
          </tbody>
        </table>
      </div>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { canonical } = ownProps;
  const model = selectModel(state);
  const entities = (canonical?.entities || []).map((e) => model.getEntity(e));

  // Each entity is paired against the canonical (NK-*) for pairwise judgement.
  // All are "positive" since they belong to this cluster.
  // Use an explicit object with the canonical ID to avoid stale entity references.
  const canonicalMatch = { id: canonical?.id };
  const items = entities.map((entity) => ({
    entity,
    match: canonicalMatch,
    judgement: 'positive',
    writeable: canonical?.writeable || false,
  }));
  return { items };
};

ProfileItemsMode = connect(mapStateToProps, { pairwiseJudgement })(
  ProfileItemsMode
);
ProfileItemsMode = withRouter(ProfileItemsMode);
ProfileItemsMode = injectIntl(ProfileItemsMode);
export default ProfileItemsMode;
