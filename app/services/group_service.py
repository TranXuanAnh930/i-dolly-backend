import uuid
from sqlalchemy.orm import Session
from app.schema.group import GroupCreate, GroupUpdate
from app.db.models.group import Group
from app.db.models.management_company import ManagementCompany
from app.db.models.user import Users

# Sentinel convention for this module: "not_found" = a referenced row doesn't
# exist (-> 404 in the router); "forbidden" = the row(s) exist but the caller
# is a manager acting outside their own company_id (-> 403). A plain admin
# is never scoped — only `role == "manager"` triggers the company check
# (database-design.md §4: "Not yet done" note, now done for groups/idols).

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def add_group(db: Session, group: GroupCreate, current_user: Users):
    if _manager_scope_violation(current_user, group.company_id):
        return "forbidden"
    company = db.get(ManagementCompany, group.company_id)
    if not company:
        return "not_found"  # company_id doesn't exist
    db_group = Group(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group

def get_groups(db: Session):
    result = db.query(Group).all()
    if not result:
        return False
    return result

def get_group(db: Session, id: uuid.UUID):
    return db.get(Group, id)

def update_group(db: Session, id: uuid.UUID, data: GroupUpdate, current_user: Users):
    db_group = db.get(Group, id)
    if not db_group:
        return "not_found"
    if _manager_scope_violation(current_user, db_group.company_id):
        return "forbidden"
    db_group.name = data.name
    db_group.debut_date = data.debut_date
    db_group.description = data.description
    db.commit()
    db.refresh(db_group)
    return db_group

def delete_group(db: Session, id: uuid.UUID, current_user: Users):
    db_group = db.get(Group, id)
    if not db_group:
        return "not_found"
    if _manager_scope_violation(current_user, db_group.company_id):
        return "forbidden"
    db.delete(db_group)
    db.commit()
    return True
