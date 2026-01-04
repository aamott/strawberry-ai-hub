import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Trash2, UserPlus, Shield } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";

interface User {
    id: string;
    username: string;
    is_admin: boolean;
    created_at: string;
    last_login?: string;
}

export function UsersPage() {
    const [users, setUsers] = useState<User[]>([]);
    const [open, setOpen] = useState(false);
    const [newUser, setNewUser] = useState({
        username: "",
        password: "",
        is_admin: false,
    });
    const { toast } = useToast();

    const loadUsers = async () => {
        try {
            const res = await api.get("/users");
            setUsers(res.data);
        } catch (err) {
            toast({
                title: "Error",
                description: "Failed to load users",
                variant: "destructive",
            });
        }
    };

    useEffect(() => {
        loadUsers();
    }, []);

    const handleDelete = async (id: string) => {
        if (!confirm("Are you sure you want to delete this user?")) return;
        try {
            await api.delete(`/users/${id}`);
            toast({ title: "User deleted" });
            loadUsers();
        } catch (err: any) {
            toast({
                title: "Error",
                description: err.response?.data?.detail || "Failed to delete user",
                variant: "destructive",
            });
        }
    };

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();

        try {
            await api.post("/users", newUser);
            toast({ title: "User created" });
            setOpen(false);
            setNewUser({ username: "", password: "", is_admin: false });
            loadUsers();
        } catch (err: any) {
            toast({
                title: "Error",
                description: err.response?.data?.detail || "Failed to create user",
                variant: "destructive",
            });
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">Users</h2>
                    <p className="text-muted-foreground">Manage users and administrators.</p>
                </div>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogTrigger asChild>
                        <Button>
                            <UserPlus className="mr-2 h-4 w-4" />
                            Add User
                        </Button>
                    </DialogTrigger>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle>Add New User</DialogTitle>
                            <DialogDescription>
                                Create a new user. Admin access is optional.
                            </DialogDescription>
                        </DialogHeader>
                        <form onSubmit={handleCreate}>
                            <div className="grid gap-4 py-4">
                                <div className="grid gap-2">
                                    <Label htmlFor="username">Username</Label>
                                    <Input
                                        id="username"
                                        value={newUser.username}
                                        onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                                        required
                                    />
                                </div>
                                <div className="grid gap-2">
                                    <Label htmlFor="password">Password</Label>
                                    <Input
                                        id="password"
                                        type="password"
                                        value={newUser.password}
                                        onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                                        required
                                    />
                                </div>
                                <div className="flex items-center gap-2">
                                    <input
                                        id="is_admin"
                                        type="checkbox"
                                        className="h-4 w-4 rounded border border-input bg-background text-primary ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                                        checked={newUser.is_admin}
                                        onChange={(e) =>
                                            setNewUser({ ...newUser, is_admin: e.target.checked })
                                        }
                                    />
                                    <Label htmlFor="is_admin">Admin</Label>
                                </div>
                            </div>
                            <DialogFooter>
                                <Button type="submit">Create User</Button>
                            </DialogFooter>
                        </form>
                    </DialogContent>
                </Dialog>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {users.map((user) => (
                    <Card key={user.id}>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">
                                {user.username}
                            </CardTitle>
                            {user.is_admin && <Shield className="h-4 w-4 text-muted-foreground" />}
                        </CardHeader>
                        <CardContent>
                            <div className="text-xs text-muted-foreground mt-2">
                                Created: {new Date(user.created_at).toLocaleDateString()}
                            </div>
                            <div className="text-xs text-muted-foreground">
                                Last Login: {user.last_login ? new Date(user.last_login).toLocaleDateString() : "Never"}
                            </div>
                            <div className="mt-4 flex justify-end">
                                <Button variant="destructive" size="sm" onClick={() => handleDelete(user.id)}>
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </div>
        </div>
    );
}
