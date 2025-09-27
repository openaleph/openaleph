# Understanding Permissions

OpenAleph uses a deliberately simple permissions model with only two access levels, that can be applied on a per-collection level. This design choice keeps the system manageable while covering most common use cases without the complexity of granular permission systems.

### Permission Levels

**Read Access**

- View collection contents and documents
- Search and browse entities
- View entity sets, such as network diagrams
- Download individual documents
- View investigation workspaces shared with you

**Write Access**
All of the above, plus:

- Upload new documents and datasets
- Edit collection metadata and descriptions
- Modify entity information and mappings
- Create and edit network diagrams
- Add other users to the collection and change their permission levels
- Delete collections

### Admin Access

System administrators automatically have full access to all collections, regardless of individual permission settings. Admin users can:

- Access any collection without explicit permissions
- Manage system-wide settings
- Override collection-level access controls
- Convert Investigations to Datasets and vice versa
- Share collections with special user groups, such 'all logged in users'

## How Permissions Are Applied

### Collection-Level Permissions

All permissions in OpenAleph are granted at the collection level. You cannot set different permission levels for individual documents or entities within a collection - access is all-or-nothing for each collection.

### User and Group Permissions

Permissions can be granted to:

**Individual Users**

- Direct permission assignment to specific user accounts
- Useful for small teams or specific collaborations
- Simple to manage for limited numbers of users

**User Groups**

- Permissions granted to groups automatically apply to all group members
- Efficient for managing access across teams or departments
- Changes to group membership automatically update access rights

### Permission Inheritance

When a user belongs to multiple groups with different permission levels for the same collection, they receive the highest level of access granted by any group membership.

## Important Limitations

### Two-Level System Only

OpenAleph intentionally supports only read and write access levels. There are no granular permissions such as:

- View-only specific document types
- Edit metadata but not upload documents
- Partial collection access
- Time-limited access
- Any file-based or entity-based permissions

### Streaming API Access

The streaming API requires write access to collections, even for read-only operations. This technical limitation means users who only need to read data via the API must be granted write permissions, which may seem counterintuitive.

### Group Management UI

There is no built-in user interface for creating and managing groups. In production deployments, groups should be managed by the SSO solution used with OpenAleph.

## Best Practices

### Data Organization

**Separate Sensitive Data**

- Create separate collections for different sensitivity levels
- Use collection names that clearly indicate access requirements
- Regularly review collection membership

**Logical Grouping**

- Organize documents by project, team, or access requirements
- Consider future collaboration needs when creating collections
- Plan collection structure before uploading large datasets

### Access Management

**Principle of Least Privilege**

- Grant read access by default
- Only provide write access to active collaborators
- Regularly audit user permissions

**Group-Based Management**

- Use groups for team-based access whenever possible
- Organize groups by organizational structure or project teams
- Document group purposes and membership criteria

**Regular Reviews**

- Periodically review collection access lists
- Remove access for users who no longer need it
- Update permissions when team membership changes

### Investigation Workflows

**Private by Default**

- Start investigations as private workspaces
- Add collaborators incrementally as needed
- Consider data sensitivity before sharing

**Clear Naming Conventions**

- Use descriptive collection names
- Include access level indicators in names when helpful
- Maintain consistent naming across your organization

## Troubleshooting Common Issues
### Streaming API Access Issues

Remember that streaming API operations require write access, even for read-only operations. Users experiencing API access issues may need their permissions upgraded from read to write.

### Group Membership Not Working

Verify that:

- Groups are properly configured in the database
- User membership is correctly assigned
- Group permissions are set at the collection level
- The user has started a new session after being added to the group, for example by signing out and back in

---

For practical steps on sharing investigations through the user interface, see [Managing Access](manage-access.md).
