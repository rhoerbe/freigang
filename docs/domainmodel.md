# Domain Model

```classDiagram
    Project "1" -- "*" Agent
    Project "1" -- "*" ResourceGroup
    Project "1" -- "*" Resource
    ResourceGroup "1" -- "*" Resource
    Agent "*" -- "*" Policy
    Capability "*" -- "*" Policy
    Policy "*" -- "1" Resource
    Capability "1" -- "*" Skill
    Resource "1" -- "*" Credential

    class Project {
        +ProjID
        +RepoURL
    }
    class ResourceGroup {
        +ResGroupID
    }
    class Agent {
        +Description
        +Userid
    }
    class Policy {
        +int ID
        +Reason
    }
    class Capability {
        +CapabilityID
        +Description
        +Type
    }
    class Skill {
        +SkillDefinition
        +SkillTitle
    }
    class Resource {
        +Name
        +requiresAuthN
        +Type
    }
    class Credential {
        +CredentialType
        +Description
    }
```