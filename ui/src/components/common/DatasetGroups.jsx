import React, { Component } from 'react';
import DatasetGroup from './DatasetGroup';

class DatasetGroups extends Component {
  constructor(props) {
    super(props);
    this.state = { groups: null, error: false };
  }

  componentDidMount() {
    this.fetchGroups();
  }

  componentDidUpdate(prevProps) {
    if (prevProps.url !== this.props.url) {
      this.fetchGroups();
    }
  }

  fetchGroups() {
    const { url } = this.props;
    if (!url) return;

    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then((data) => this.setState({ groups: data.groups || data }))
      .catch(() => this.setState({ error: true }));
  }

  render() {
    const { groups, error } = this.state;
    if (error || !groups) return null;

    return (
      <div className="DatasetGroups">
        {groups.map((group, i) => (
          <DatasetGroup
            key={i}
            label={group.label}
            description={group.description}
            icon={group.icon}
            collections={group.collections || []}
            body={group.body}
            content={group.content}
          />
        ))}
      </div>
    );
  }
}

export default DatasetGroups;
